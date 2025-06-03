from mcp import ClientSession, StdioServerParameters, types
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
from typing_extensions import Self
from mcp.shared.context import RequestContext
from typing import Any
from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.cmd.utils import CLEAR_RIGHT, PREV_LINE
from mcp_cli_host.llm.models import GenericMsg
from mcp_cli_host.llm.models import Role
from rich.console import Console
from pydantic import FileUrl

console = Console()


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


class SamplingCallback:
    def __init__(self, provider: Provider):
        self.provider = provider

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        while True:
            try:
                messages_rec = json.dumps(
                    [msg.model_dump() for msg in params.messages], indent=2, ensure_ascii=False)
                user_confirmation = console.input(
                    f"[bold magenta]Received sampling request from Server (Type 'yes' for continue, 'no' for stop):[/bold magenta]\n[green]{messages_rec}\n[/green](yes/no): ")

                print(f"{PREV_LINE}{PREV_LINE}{CLEAR_RIGHT}")
                if not user_confirmation:
                    continue

                if user_confirmation != "yes" and user_confirmation != "no":
                    continue

                console.print(
                    f" 🤠 [bold bright_yellow]You[/bold bright_yellow]: [bold bright_white]{user_confirmation}[/bold bright_white]")

                if user_confirmation == "yes":
                    messages: list[GenericMsg] = []
                    system_message = {
                        "role": Role.SYSTEM.value,
                        "content": params.systemPrompt
                    }

                    messages.append(GenericMsg(
                        message_content=json.dumps(system_message)
                    ))
                    # mcp SamplingMessage not match the message format of openai, meed transfer
                    # the message.content in openai is either a str or list[TextContent]
                    for msg in params.messages:
                        new_msg = {
                            "role": msg.role,
                            "content": [msg.content.model_dump()],
                        }
                        messages.append(GenericMsg(
                            message_content=json.dumps(new_msg))
                        )

                    with console.status("[bold bright_magenta]Thinking...[/bold bright_magenta]"):
                        try:
                            llm_res: GenericMsg = self.provider.completions_create(
                                prompt="",
                                messages=messages,
                                tools=[],
                            )
                        except Exception:
                            raise

                    if llm_res and llm_res.usage:
                        input_token, output_token = llm_res.usage
                        log.info(
                            f"Token usage statistics: Input: {input_token}, Output: {output_token}")

                    if not llm_res:
                        log.warning("LLM response nothing, try again")
                        return types.ErrorData(
                            code=types.INVALID_REQUEST,
                            message="LLM response nothing, try again",
                        )

                    if llm_res.content and not llm_res.toolcalls:
                        return types.CreateMessageResult(
                            role="assistant",
                            content=types.TextContent(
                                type="text", text=llm_res.content),
                            model=self.provider.name(),
                            stopReason="endTurn",
                        )
                else:
                    console.print(" ❌, reject the request ")
                    return types.ErrorData(
                        code=types.INVALID_REQUEST,
                        message="User prevent the request",
                    )

            except KeyboardInterrupt:
                console.print("\n[magenta]Goodbye![/magenta]")
                break
            except Exception:
                raise


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


class RootsCallback:
    def __init__(self, roots: list[str] = None):
        self.roots = roots

    async def __call__(self,
                       context: RequestContext["ClientSession", Any],
                       ) -> types.ListRootsResult | types.ErrorData:
        
        roots: list[types.Root] = []
        if self.roots:
            for index, root in enumerate(self.roots):
                roots.append(types.Root(
                    uri=FileUrl(root if root.startswith("file://") else "file://" + root),
                    name="workspace_" + str(index),
                ))

        return types.ListRootsResult(
            roots=roots
        )


class Server:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: StdioServerParameters) -> None:
        self.name: str = name
        self.config: StdioServerParameters = config
        self.stdio_context: any | None = None
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()

    async def initialize(self, debug_model: bool = False, provider: Provider = None, roots: list[str] = None) -> None:
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
                ClientSession(read,
                              write,
                              message_handler=message_handler,
                              sampling_callback=SamplingCallback(provider),
                              list_roots_callback=RootsCallback(roots) if roots else None
                            )
            )

            initialize_result: types.InitializeResult = await session.initialize()

            if debug_model and initialize_result.capabilities.logging:
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
