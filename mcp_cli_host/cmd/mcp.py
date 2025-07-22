from mcp import ClientSession, StdioServerParameters, types
from mcp.shared.exceptions import McpError
from mcp_cli_host.cmd.stdio_client import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp_cli_host.cmd.mcp_client_functions.err_monitor import err_monitor
from mcp_cli_host.cmd.mcp_client_functions.sampling_handler import SamplingCallback
from mcp_cli_host.cmd.mcp_client_functions.notification_handler import NotificationHandler
from mcp_cli_host.cmd.mcp_client_functions.roots_handler import RootsCallback
from mcp_cli_host.cmd.mcp_client_functions.elicitation_handler import ElicitationCallback
import os
import json
from contextlib import AsyncExitStack
import asyncio
import shutil
import logging
from mcp_cli_host.llm.base_provider import Provider
from rich.console import Console
from pydantic import AnyUrl, BaseModel, AnyHttpUrl
from mcp_cli_host.cmd.utils import COMMON_SEPERATOR, PREFIX_RESOURCE_TOOL, URL_TEMPLATE_KEY
from datetime import timedelta

console = Console()


log = logging.getLogger("mcp_cli_host")

class RemoteServerParameters(BaseModel):
    url: str | AnyHttpUrl | None = None,
    """The URL where the MCP server is accessible."""

    headers: dict[str, str] | None = None
    """ (Optional) Array of HTTP headers for authentication and custom headers"""

class Server:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: StdioServerParameters | RemoteServerParameters) -> None:
        self.name: str = name
        self.config: StdioServerParameters | RemoteServerParameters = config
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()

    async def initialize(self, debug_model: bool = False, provider: Provider = None, roots: list[str] = None) -> types.InitializeResult | None:
        """Initialize the server connection."""
        try:
            if isinstance(self.config, RemoteServerParameters):
                # For remote server, we use the streamablehttp_client to create a connection
                log.info(f"Connecting to remote server {self.name} at {self.config.url}")
                remote_transport = await self.exit_stack.enter_async_context(
                    streamablehttp_client(self.config.url, 
                                          headers=self.config.headers,
                                          timeout=timedelta(seconds=60),)
                )
                read, write, get_session_id = remote_transport
            else:
                # For local server, we use the stdio_client to create a connection
                log.info(f"Connecting to local server {self.name}")
                stdio_transport = await self.exit_stack.enter_async_context(
                    stdio_client(self.config)
                )
                read, write, err = stdio_transport

                _ = await self.exit_stack.enter_async_context(
                    err_monitor(err)
                )

            session = await self.exit_stack.enter_async_context(
                ClientSession(read,
                              write,
                              message_handler=NotificationHandler(),
                              sampling_callback=SamplingCallback(provider),
                              list_roots_callback=RootsCallback(roots) if roots else None,
                              elicitation_callback=ElicitationCallback()
                            )
            )

            initialize_result: types.InitializeResult = await session.initialize()

            if debug_model and initialize_result.capabilities.logging:
                try:
                    await session.set_logging_level("debug")
                except McpError as e:
                    log.warning(f"Failed to set logging level to debug: {e}")

            self.session = session
            return initialize_result
        except Exception as e:
            print(type(e))
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
                    name=f"{self.name}{COMMON_SEPERATOR}{tool.name}",
                    description=tool.description,
                    inputSchema=tool.inputSchema)
            )

        return tools

    async def execute_tool(
        self,
        tool: types.Tool,
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
        
        tool_name: str = tool.name.split(COMMON_SEPERATOR)[1]
        # handle the tools generated by resource template
        if tool_name.startswith(PREFIX_RESOURCE_TOOL):
            # Extract the resource URI from the tool name
            resource_uri = tool.meta.get(URL_TEMPLATE_KEY, None)
            resource_uri = resource_uri.format(**arguments)
            log.info(f"Executing resource tool: {resource_uri}")

            try:
                # Read the resource
                read_result: types.ReadResourceResult = await self.get_resource(
                    uri=resource_uri, retries=retries, delay=delay
                )
            except Exception as e:
                log.error(
                    f"Error executing tool: {e}."
                )
                return types.CallToolResult(
                    content = [],
                    isError = True,
                )

            return types.CallToolResult(
                content = [types.TextContent(type="text", text=content.text) for content in read_result.contents],
                isError = False,
            )
        
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

    async def list_resources(self) -> list[types.Resource]:
        """List available resources from the server.

        Returns:
            A list of available resources.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        resources_response: types.ListResourcesResult = await self.session.list_resources()
        resources: list[types.Resource] = []

        for resource in resources_response.resources:
            resources.append(
                types.Resource(
                    name=f"{self.name}{COMMON_SEPERATOR}{resource.name}",
                    description=resource.description,
                    uri=resource.uri,
                    size=resource.size,
                )
            )

        return resources

    async def list_resource_templates(self) -> list[types.ResourceTemplate]:
        """List available resource templates from the server.

        Returns:
            A list of available resource templates.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        resource_templates_response: types.ListResourceTemplatesResult = await self.session.list_resource_templates()
        resource_templates: list[types.ResourceTemplate] = []

        for resource_template in resource_templates_response.resourceTemplates:
            resource_templates.append(
                types.ResourceTemplate(
                    name=f"{self.name}{COMMON_SEPERATOR}{resource_template.name}",
                    description=resource_template.description,
                    uriTemplate=resource_template.uriTemplate,
                )
            )

        return resource_templates
    
    async def get_resource(
        self,
        uri: str,
        retries: int = 2,
        delay: float = 1.0,
    ) -> types.ReadResourceResult:
        """Read a resource with retry mechanism.

        Args:
            uri: uri of the resource to read.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            read resource result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        attempt = 0
        while attempt < retries:
            try:
                log.info(f":📖:read resource: [{uri}]...")
                result: types.ReadResourceRequest = await self.session.read_resource(AnyUrl(uri))

                return result

            except Exception as e:
                attempt += 1
                log.warning(
                    f"Error reading resource: {e}. Attempt {attempt} of {retries}."
                )
                if attempt < retries:
                    log.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    log.error("Max retries reached. Failing.")
                    raise

    async def list_prompts(self) -> list[types.Prompt]:
        """List available prompts from the server.

        Returns:
            A list of available prompts.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        prompts_response: types.ListPromptsResult = await self.session.list_prompts()
        prompts: list[types.Prompt] = []

        for prompt in prompts_response.prompts:
            prompts.append(
                types.Prompt(
                    name=f"{self.name}{COMMON_SEPERATOR}{prompt.name}",
                    description=prompt.description,
                    arguments=prompt.arguments,
                )
            )

        return prompts
    
    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str],
        retries: int = 2,
        delay: float = 1.0,
    ) -> types.GetPromptResult:
        """Read a prompt with retry mechanism.

        Args:
            name: name of the prompt to read.
            arguments: arguments for the prompt.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            read prompt result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        attempt = 0
        while attempt < retries:
            try:
                log.info(f":📄:read prompt: [{name}]...")
                result: types.GetPromptResult = await self.session.get_prompt(name, arguments)

                return result

            except Exception as e:
                attempt += 1
                log.warning(
                    f"Error reading resource: {e}. Attempt {attempt} of {retries}."
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
            except Exception as e:
                log.error(f"Error during cleanup of server {self.name}: {e}")
                raise


def load_mcp_config(server_conf_path: str = None) -> dict[str, StdioServerParameters | RemoteServerParameters]:
    servers: dict[str, StdioServerParameters | RemoteServerParameters] = {}
    if not server_conf_path:
        home = os.path.expanduser("~")
        server_conf_path = os.path.join(home, ".mcp.json")

    try:
        with open(server_conf_path, 'r') as f:
            data = json.load(f)
            servers = data["mcpServers"]

        assert type(servers) is dict
        for server_name, server_conf in servers.items():
            if "url" in server_conf:
                # Remote server configuration
                servers[server_name] = RemoteServerParameters(
                    url=server_conf["url"],
                    headers=server_conf.get("headers", None)
                )
                continue 

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
