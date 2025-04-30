from mcp_cli_host.llm.azure.provider import Azure
from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.llm.models import GenericMsg, Role, CallToolResultWithID, TextContent
from mcp_cli_host.cmd.mcp import load_mcp_config, Server
from mcp_cli_host.console import console
from mcp import types, StdioServerParameters
import json
import logging
import asyncio
import argparse
import os
from rich.logging import RichHandler

FORMAT = "%(asctime)s - %(message)s"
logging.basicConfig(
    level="INFO", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)]
)

log = logging.getLogger(__name__)


class ChatSession:
    def __init__(self,
                 model: str,
                 server_conf_path: str = None,
                 openai_url: str = None,
                 message_window: int = 10,
                 debug_model: bool = False,
                 ) -> None:
        self.model = model
        self.server_conf_path = server_conf_path
        self.openai_url = openai_url
        self.message_window = message_window
        self.debug_model = debug_model
        self.servers: dict[str, Server] = None

    async def run_promt(self,
                        provider: Provider,
                        prompt: str,
                        messages: list[GenericMsg],
                        tools: list[types.Tool]):

        if prompt != "":
            message = {
                "role": Role.USER.value,
                "content": prompt
            }

            # Push promot from user
            messages.append(
                GenericMsg(message_content=json.dumps(message))
            )
        with console.status("Thinking...", spinner="clock"):
            try:
                llm_res: GenericMsg = provider.completions_create(
                    prompt=prompt,
                    messages=messages,
                    tools=tools,
                )
            except Exception:
                raise

        input_token, output_token = llm_res.usage
        log.info(
            f"Token usage statistics: Input: {input_token}, Output: {output_token}")

        if not llm_res:
            log.warning("LLM response nothing, try again")
            return

        # Push response from LLM, could be tool_calls or just text
        messages.append(llm_res)
        if llm_res.content:
            console.print("\n 🤖 Asistant:\n")
            console.print(llm_res.content, highlight=False,
                          new_line_start=True)
            console.print("\n\n")
            return

        tool_call_results: list[CallToolResultWithID] = []
        for tool_call in llm_res.toolcalls:
            id = tool_call.id
            name = tool_call.name
            arguments = tool_call.arguments

            server_name, tool_name = name.split("__")
            if not server_name or not tool_name:
                raise ValueError(f"Invalid tool name format: {name}")

            server = self.servers.get(server_name, None)
            if not server:
                raise ValueError(f"Server not found: {server_name}")

            tool_call_res: types.CallToolResult = await server.execute_tool(
                tool_name=tool_name,
                arguments=arguments
            )

            if tool_call_res.isError:
                log.warning(
                    f"Error executing tool: {tool_name}, error is: {tool_call_res.content}")
                return

            contents: list[TextContent] = []
            for content in tool_call_res.content:
                contents.append(TextContent(
                    type=content.type,
                    text=content.text
                ))

            result = CallToolResultWithID(
                tool_call_id=id,
                name=name,
                content=contents,
                isError=tool_call_res.isError
            )

            tool_call_results.append(result)
        # Push tool excution result
        messages.append(GenericMsg(
            message_content=tool_call_results
        ))

        if len(tool_call_results) > 0:
            await self.run_promt(
                provider=provider,
                prompt="",
                messages=messages,
                tools=tools
            )

    async def cleanup_servers(self) -> None:
        """Clean up all servers properly."""
        for name, server in self.servers.items():
            log.info(f"Shutting down MCP server: [{name}]")
            await server.cleanup()

    def create_provider(self) -> Provider:
        if ":" not in self.model:
            raise ValueError("Invalid format! Expected format is 'a:b'")

        provider, model = self.model.split(":")
        log.info(f"Model loaded: Provider: [{provider}] Model: [{model}]")

        if provider == "openai":
            api_key = os.environ.get('OPENAI_API_KEY', '')
            if api_key == "":
                raise ValueError(
                    'Environment variable OPENAI_API_KEY not found or its value is empty.')
            return None  # TODO

        elif provider == "azure":
            azure_deploy = os.environ.get('AZURE_OPENAI_DEPLOYMENT', '')
            azure_api_key = os.environ.get('AZURE_OPENAI_API_KEY', '')
            azure_api_version = os.environ.get('AZURE_OPENAI_API_VERSION', '')
            azure_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT', '')

            if azure_deploy == "" or azure_api_key == "" or azure_api_version == "" or azure_endpoint == "":
                raise ValueError(
                    "environment variables missing\n, need 'AZURE_OPENAI_DEPLOYMENT', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_API_VERSION' and 'AZURE_OPENAI_ENDPOINT'.")

            return Azure(model=model)

        elif provider == "ollama":
            ...

        raise ValueError(
            "Unsupport provider: {provider}, should be in ['openai', 'azure', 'ollama']")

    async def run_mcp_host(self):
        # use register to supply the provider TODO
        provider = self.create_provider()

        mcpserver_confs: dict[str, StdioServerParameters] = load_mcp_config(
            server_conf_path=self.server_conf_path)

        self.servers = {
            name: Server(name, srv_config)
            for name, srv_config in mcpserver_confs.items()
        }

        for name, server in self.servers.items():
            try:
                log.info(f"Initializing server... [{name}]")
                await server.initialize()
                log.info(f"Server connected: [{name}]")
            except Exception as e:
                await self.cleanup_servers()
                raise RuntimeError(
                    f"Failed to initialize server {name}") from e

        tools: list[types.Tool] = []
        for name, server in self.servers.items():
            if not server:
                raise RuntimeError(f"Server {name} not initialized")

            tools_response: list[types.Tool] = await server.list_tools()
            tools.extend(tools_response)

        log.info(f"Tools loaded, total count: {len(tools)}")
        history_message: list[GenericMsg] = []
        try:
            while True:
                try:
                    user_input = console.input(
                        "[bold magenta]Enter your prompt (Type /help for commands, Ctrl+C to quit)[/bold magenta]\n")
                    if user_input in ["quit", "exit"]:
                        logging.info("\nExiting...")
                        break
                    await self.run_promt(
                        provider=provider,
                        prompt=user_input,
                        messages=history_message,
                        tools=tools,
                    )

                except KeyboardInterrupt:
                    logging.info("\nExiting...")
                    break
        except Exception:
            raise
        finally:
            await self.cleanup_servers()


async def main() -> None:
    """Initialize and run the chat session."""
    parser = argparse.ArgumentParser(prog='mcphost', description="")
    parser.add_argument('--config', required=False,
                        help="config file (default is $HOME/mcp.json)")
    parser.add_argument('--message-window', required=False, type=int,
                        default=10, help="number of messages to keep in context")
    parser.add_argument('-m', '--model', required=True,
                        help="model to use (format: provider:model, e.g. azure:gpt-4-0613 or ollama:qwen2.5:3b)")
    parser.add_argument('--debug', required=False,
                        action="store_true", help="enable debug logging")
    parser.add_argument('--openai-url', required=False,
                        help="base URL for OpenAI API (defaults to api.openai.com)")
    args = parser.parse_args()

    if args.debug:
        FORMAT = "%(asctime)s - %(name)s - %(message)s"
        logging.basicConfig(
            level="DEBUG", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)]
        )

    try:
        # await run_mcp_host(model=args.model, server_conf_path=args.config, openai_url=args.openai_url, message_window=args.message_window, debug_model=args.debug)
        chat_session = ChatSession(
            model=args.model,
            server_conf_path=args.config,
            openai_url=args.openai_url,
            message_window=args.message_window,
            debug_model=args.debug)
        
        await chat_session.run_mcp_host()
    except Exception as e:
        log.error(f"{e}")
        parser.print_help()


if __name__ == '__main__':
    asyncio.run(main())
