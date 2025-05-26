from mcp import ClientSession, StdioServerParameters, types
# from mcp.client.stdio import stdio_client
from mcp_cli_host.cmd.stdio_client import stdio_client
from mcp.shared.session import RequestResponder
import os
import json
from contextlib import AsyncExitStack
import asyncio
import shutil
import logging
import anyio
from types import TracebackType
from anyio.streams.memory import MemoryObjectReceiveStream
from typing_extensions import Self, Optional


log = logging.getLogger("mcp_cli_host")

class ERRMonitor:
    def __init__(
        self,
        read_stderr: MemoryObjectReceiveStream,
    ):
        self.read_stderr = read_stderr

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._monitor_server_stderr)
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        if self._task_group:
            return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        return None
         
    async def _monitor_server_stderr(self):
        async with (
            self.read_stderr,
        ):
            async for message in self.read_stderr:
                log.debug(
                    "👻 Received err from server: %s", message.decode() if isinstance(message, bytes) else message)

async def message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult]
    | types.ServerNotification
    | Exception
    | str
) -> None:
    if isinstance(message, Exception):
        log.error("Error: %s", message)
        return
    if isinstance(message, types.ServerNotification):
        if isinstance(message.root, types.LoggingMessageNotification):
            message_obj: types.LoggingMessageNotification = message.root
            log.debug(
                "📩 Received log notification message from server: %s", message_obj.params.data)


class Server:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: StdioServerParameters) -> None:
        self.name: str = name
        self.config: StdioServerParameters = config
        self.stdio_context: any | None = None
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()
    
    async def initialize(self, debug_model: bool = False) -> None:
        """Initialize the server connection."""
        try:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(self.config)
            )
            read, write, err = stdio_transport

            _ = await self.exit_stack.enter_async_context(
                ERRMonitor(err)
            )

            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write, message_handler=message_handler)
            )

            await session.initialize()
            if debug_model:
                await session.set_logging_level("debug")

            self.session = session
        except Exception as e:
            log.error(f"Error initializing server {self.name}: {e}")
            await self.cleanup()
            raise

    async def list_tools(self) -> list[types.Tool]:
        """List available tools from the server.

        Returns:
            A list of available tools.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        tools_response: types.ListToolsResult = await self.session.list_tools()
        tools: list[types.Tool] = []

        for tool in tools_response.tools:
            tools.append(
                types.Tool(
                    name=f"{self.name}__{tool.name}",
                    description=tool.description,
                    inputSchema=tool.inputSchema)
            )

        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, any],
        retries: int = 2,
        delay: float = 1.0,
    ) -> types.CallToolResult:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        attempt = 0
        while attempt < retries:
            try:
                log.info(f":🔧:Executing tool: [{tool_name}]...")
                result: types.CallToolResult = await self.session.call_tool(tool_name, arguments)

                return result

            except Exception as e:
                attempt += 1
                log.warning(
                    f"Error executing tool: {e}. Attempt {attempt} of {retries}."
                )
                if attempt < retries:
                    log.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    log.error("Max retries reached. Failing.")
                    raise

    async def cleanup(self) -> None:
        """Clean up server resources."""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
                self.stdio_context = None
            except Exception as e:
                log.error(f"Error during cleanup of server {self.name}: {e}")
                raise


def load_mcp_config(server_conf_path: str = None) -> dict[str, StdioServerParameters]:
    servers: dict[str, StdioServerParameters] = {}
    if not server_conf_path:
        home = os.path.expanduser("~")
        server_conf_path = os.path.join(home, ".mcp.json")

    try:
        with open(server_conf_path, 'r') as f:
            data = json.load(f)
            servers = data["mcpServers"]

        assert type(servers) is dict
        for server_name, server_conf in servers.items():
            command = server_conf["command"]
            if not os.path.isabs(command):
                command = shutil.which(command)

            if command is None:
                raise ValueError(
                    "The command must be a valid existed path and cannot be None.")

            servers[server_name] = StdioServerParameters(
                command=command,
                args=server_conf["args"],
                env={**os.environ, **server_conf["env"]}
                if server_conf.get("env")
                else None,
            )

        return servers
    except Exception as e:
        print(f"Error loading mcp server configuration file: {e}")
        raise
