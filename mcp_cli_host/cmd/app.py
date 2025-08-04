from mcp_cli_host.llm.gemini.provider import Gemini
from mcp_cli_host.llm.models import GenericMsg
from mcp_cli_host.llm.azure.provider import Azure
from mcp_cli_host.llm.openai.provider import Openai
from mcp_cli_host.llm.deepseek.provider import Deepseek
from mcp_cli_host.llm.ollama.provider import Ollama
from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.llm.models import Role, CallToolResultWithID, TextContent
from mcp_cli_host.cmd.mcp import load_mcp_config, Server
from mcp_cli_host.console import console
from mcp_cli_host.cmd.utils import CLEAR_RIGHT, PREV_LINE, MARKDOWN, prune_messages, format_server_card, generated_tools_from_resource_templates, COMMON_SEPERATOR
from mcp import types, StdioServerParameters, shared
import json
import logging
import asyncio
import argparse
from rich.logging import RichHandler
from rich.highlighter import NullHighlighter
import os
from rich.markdown import Markdown
import traceback
from collections import defaultdict
from typing import Tuple, Union, List, Literal

log = logging.getLogger("mcp_cli_host")


class ChatSession:
    def __init__(self,
                 model: str,
                 server_conf_path: str = None,
                 openai_url: str = None,
                 message_window: int = 10,
                 debug_model: bool = False,
                 roots: list[str] = None,
                 sys_prompt: str = None
                 ) -> None:
        self.model = model
        self.server_conf_path = server_conf_path
        self.openai_url = openai_url
        self.message_window = message_window
        self.debug_model = debug_model
        self.servers: dict[str, Server] = None
        self.history_message: list[GenericMsg] = []
        self.roots = roots
        self.sys_prompt = sys_prompt
        self.tools: list[types.Tool] = []
        self.resource_tools: list[types.Tool] = []
        self.excluded_tools: list[str] = []
        self.initialize_results: dict[str, types.InitializeResult] = {}
        self.resources = defaultdict(list)
        self.prompts: list[types.Prompt] = []
        # Put system prompt on the top of the history if exists
        if self.sys_prompt:
            sys_prompt_message = {
                "role": Role.SYSTEM.value,
                "content": self.sys_prompt
            }
            self.history_message.append(
                GenericMsg(message_content=json.dumps(sys_prompt_message))
            )

    async def handle_slash_command(self, prompt: str) -> Union[
        Tuple[Literal[True], None],
        Tuple[Literal[False], None],
        Tuple[Literal[True], List[any]]
    ]:
        if not prompt.startswith("/"):
            return (False, None)
        
        if prompt.lower().strip() == "/tools":
            for name, server in self.servers.items():
                console.print(f"[magenta]💻 {name}[/magenta]")
                if not self.initialize_results.get(name).capabilities.tools and len(self.resource_tools) == 0:
                    console.print(f"  [red] 🚫 Server {name} does not support tools.[/red]\n")
                    continue
                
                if self.initialize_results.get(name).capabilities.tools:
                    for tool in await server.list_tools():
                        excluded = tool.name in self.excluded_tools
                        tool_name = tool.name.split(COMMON_SEPERATOR)[1]
                        if excluded:
                            console.print(f"  [bright_red] 🚫 {tool_name} (excluded)[/bright_red]")
                        else:
                            console.print(f"  [bright_cyan] 🔧 {tool_name}[/bright_cyan]")
                        console.print(f"    [bright_blue] {tool.description}[/bright_blue]")
                
                if len(self.resource_tools) > 0:
                    resource_tools = [
                        tool for tool in self.resource_tools if tool.name.startswith(name + COMMON_SEPERATOR)]
                    for tool in resource_tools:
                        excluded = tool.name in self.excluded_tools
                        tool_name = tool.name.split(COMMON_SEPERATOR)[1]
                        if excluded:
                            console.print(f"  [bright_red] 🚫 {tool_name} (excluded)[/bright_red]")
                        else:
                            console.print(f"  [bright_cyan] 🔧 {tool_name} (by resource templates)[/bright_cyan]")
                        console.print(f"    [bright_blue] {tool.description}[/bright_blue]")
                console.print("\n")

            return (True, None)
        
        if prompt.lower().strip() == "/help":
            console.print(Markdown(MARKDOWN))
            return (True, None)
        
        if prompt.lower().strip() == "/history":
            console.print(self.history_message)
            return (True, None)
        
        if prompt.lower().strip() == "/servers":
            for name, server in self.servers.items():
                console.print(f"\n\n[magenta]💻 {name}[/magenta]\n")
                console.print(f"[while]Command[while] [green]{server.config.command}\n")
                console.print(f"[while]Arguments[while] [green]{server.config.args}\n\n")
            return (True, None)
        
        if prompt.lower().startswith("/exclude_tool"):
            if len(prompt.split()) < 2:
                console.print("[red][bold]ERROR[/bold]: Missing tool name to exclude[/red]\n")
                return (True, None)
            
            tool_name = prompt.split()[1]
            self.excluded_tools.extend([tool.name for tool in self.tools if tool.name.endswith(tool_name)])
            self.tools = [tool for tool in self.tools if not tool.name.endswith(tool_name)]
            console.print(f"[green]Tool '{tool_name}' excluded successfully.[/green]\n")
            return (True, None)

        if prompt.lower().startswith("/resources"):
            for name, server in self.servers.items():
                console.print(f"[magenta] 📚 {name}[/magenta]")
                if not self.initialize_results.get(name).capabilities.resources:
                    console.print(f"  [red] 🚫 Server {name} does not support resources.[/red]\n")
                    continue
                
                for resource in await server.list_resources():

                    resource_name = resource.name.split(COMMON_SEPERATOR)[1]
                    console.print(f"  [bright_cyan] 📖 {resource_name}[/bright_cyan]")
                    console.print(f"    [bright_blue] {resource.description}[/bright_blue]")
                    console.print(f"    [bright_blue] [bright_cyan]URI[/bright_cyan]: {resource.uri}[/bright_blue]")
                    console.print(f"    [bright_blue] [bright_cyan]size[/bright_cyan]: {resource.size}[/bright_blue]")
                console.print("\n")
            return (True, None)
        
        if prompt.lower().startswith("/get_resource"):
            if len(prompt.split()) < 2:
                console.print("[red][bold]ERROR[/bold]: Missing resource URI to get[/red]\n")
                return (True, None)
            
            server_input = None
            uri = prompt.split()[1]
            if COMMON_SEPERATOR in uri:
                server_input, uri = uri.split(COMMON_SEPERATOR)  # Handle server--uri format

            server_name = self.resources[uri]
            if len(server_name) == 0:
                console.print(f"[red][bold]ERROR[/bold]: Resource {uri} not found in any server.[/red]\n")
                return (True, None)
            
            if len(server_name) > 1 and not server_input:
                console.print(f"[yellow]Multiple servers found for resource {uri}: {', '.join(server_name)}[/yellow]\n")
                console.print(f"[yellow]Please use '{COMMON_SEPERATOR}' to link server name and uri and try again, like this: server{COMMON_SEPERATOR}{uri}[/yellow]\n")
                return (True, None)
            
            if server_input and server_input not in server_name:
                console.print(f"[red][bold]ERROR[/bold]: Server {server_input} not found for resource {uri}.[/red]\n")
                return (True, None)

            server_name = server_input if server_input else server_name[0]
            server = self.servers.get(server_name, None)
            if not server:
                console.print(f"[red][bold]ERROR[/bold]: Server {server_name} not found.[/red]\n")
                return (True, None)
                
            try:
                resource = await server.get_resource(uri)
                console.print(f"[green]Succeed get {len(resource.contents)} items from Server: '{server_name}' with URI: {uri}\n")
                # Check if the resource content is of type TextResourceContents
                for index, content in enumerate(resource.contents):
                    if isinstance(content, types.TextResourceContents):
                        markdown_text = f"{index}. : {content.text}"
                        console.print(Markdown(markdown_text))
            except Exception as e:
                console.print(f"[red]Error fetching resource from {server_name}: {e}[/red]\n")
            return (True, None)

        if prompt.lower().strip() == "/quit":
            raise KeyboardInterrupt()
        
        if prompt.lower().strip() == "/prompts":
            for name, server in self.servers.items():
                console.print(f"[magenta] 📑 {name}[/magenta]")
                if not self.initialize_results.get(name).capabilities.prompts:
                    console.print(f"  [red] 🚫 Server {name} does not support prompts.[/red]\n")
                    continue
                
                for prot in await server.list_prompts():
                    prompt_name = prot.name.split(COMMON_SEPERATOR)[1]
                    console.print(f"  [bright_cyan] 📄 {prompt_name}[/bright_cyan]")
                    console.print(f"    [bright_blue] {prot.description}[/bright_blue]")
                    for argument in prot.arguments:
                        console.print(f"      [bright_yellow][bright_cyan]{argument.name}[/bright_cyan]: {'(Required)' if argument.required else '(optional)'}[/bright_yellow]")
                        console.print(f"      [bright_blue]{argument.description}[/bright_blue]")

                console.print("\n")
            return (True, None)
        
        if prompt.lower().strip().startswith("/get_prompt"):
            if len(prompt.split()) < 2:
                console.print("[red][bold]ERROR[/bold]: Missing prompt name to get[/red]\n")
                return (True, None)
            
            server_input = None
            name = prompt.split()[1]
            if COMMON_SEPERATOR in name:
                server_input, name = name.split(COMMON_SEPERATOR)  # Handle server--name format

            candidate_prompts = [
               prot for prot in self.prompts if prot.name.endswith(name)]
            
            if len(candidate_prompts) == 0:
                console.print(f"[red][bold]ERROR[/bold]: Prompt {name} not found in any server.[/red]\n")
                return (True, None)
            
            if len(candidate_prompts) > 1 and not server_input:
                console.print(f"[yellow]Multiple servers found for prompt {name}: {', '.join(server_name)}[/yellow]\n")
                console.print(f"[yellow]Please use '{COMMON_SEPERATOR}' to link server name and prompt name and try again, like this: server{COMMON_SEPERATOR}{name}[/yellow]\n")
                return (True, None)
            
            if server_input and server_input not in server_name:
                console.print(f"[red][bold]ERROR[/bold]: Server {server_input} not found for prompt {name}.[/red]\n")
                return (True, None)

            server_name = server_input if server_input else candidate_prompts[0].name.split(COMMON_SEPERATOR)[0]
            server = self.servers.get(server_name, None)
            if not server:
                console.print(f"[red][bold]ERROR[/bold]: Server {server_name} not found.[/red]\n")
                return (True, None)
                
            try:
                target_prompt = candidate_prompts[0]
                args: dict[str, str] = {}
                prompt_messages: list[types.PromptMessage] = []
                while True:
                    try:
                        if target_prompt.arguments and len(target_prompt.arguments) > 0:
                            console.print(f"[bold magenta]To get prompt: [bright_blue]{target_prompt.name}[/bright_blue], you need fill arguments of the prompt: [bright_blue]{[arg.name for arg in target_prompt.arguments]}[/bright_blue][/bold magenta]")
                            for arg in target_prompt.arguments:
                                user_input = console.input(
                                    f"[bold magenta]Please input value for argument [bright_blue]'{arg.name}'[/bright_blue] (required: [bright_blue]{arg.required}[/bright_blue], description: [bright_blue]{arg.description}[/bright_blue]):\n[/bold magenta]")
                                
                                if not user_input and arg.required:
                                    console.print(f"[red]Argument '{arg.name}' is required, please input a value.[/red]")
                                    continue
                                
                                # Fill the argument value
                                args[arg.name] = user_input

                        prompt_result: types.GetPromptResult = await server.get_prompt(
                            name=target_prompt.name.split(COMMON_SEPERATOR)[1],
                            arguments=args
                        )
                        prompt_messages = prompt_result.messages
                        messages_rec = json.dumps(
                            [msg.model_dump() for msg in prompt_messages], indent=2, ensure_ascii=False)
                        console.print(f"[green]Succeed get prompt from Server: '{server_name}' with name: {target_prompt.name.split(COMMON_SEPERATOR)[1]}\n")   
                        console.print(messages_rec)
                        break
                    except KeyboardInterrupt:
                        console.print("\n")
                        return (True, None)
                    except Exception:
                        raise

                while True:
                    try:
                        user_confirmation = console.input(
                            "[bold magenta]Do you want send above messages to LLM? (Type 'yes' for send, 'no' for quit): [/bold magenta]")
                        print(f"{PREV_LINE}{CLEAR_RIGHT}")

                        if not user_confirmation:
                            continue

                        if user_confirmation != "yes" and user_confirmation != "no":
                            continue

                        console.print(
                            f" 🤠 [bold bright_yellow]You[/bold bright_yellow]: [bold bright_white]{user_confirmation}[/bold bright_white]")

                        if user_confirmation == "yes":
                            messages: list[any] = []
                            for message in prompt_messages:
                                new_msg = {
                                    "role": message.role,
                                    "content": message.content.text if isinstance(message.content, types.TextContent) else message.content.model_dump(),
                                }
                                messages.append(new_msg)
                            return (False, messages)
                        else:
                            return (True, None)
                    except KeyboardInterrupt:
                        console.print("\n")
                        return (True, None)
                    except Exception:
                        raise

            except Exception as e:
                console.print(f"[red]Error fetching prompt from {server_name}: {e}[/red]\n")
            return (True, None)
        
        console.print(f"[red][bold]ERROR[/bold]: Unkonw command: {prompt}[/red]\nType /help to see available commands\n\n")
        return (True, None)

    async def run_promt(self,
                        provider: Provider,
                        prompt: str,
                        messages: list[any] = None) -> None:

        if prompt != "":
            message = {
                "role": Role.USER.value,
                "content": prompt
            }

            # Push promot from user
            self.history_message.append(
                GenericMsg(message_content=json.dumps(message))
            )

        if messages:
            # If messages are provided, add them to the history
            self.history_message.extend([
                GenericMsg(message_content=json.dumps(msg)) for msg in messages
            ])

        with console.status("[bold bright_magenta]Thinking...[/bold bright_magenta]"):
            try:
                llm_res: GenericMsg = provider.completions_create(
                    prompt=prompt,
                    messages=self.history_message,
                    tools=self.tools,
                )
            except Exception:
                raise

        if llm_res and llm_res.usage:
            input_token, output_token = llm_res.usage
            log.info(
                f"Token usage statistics: Input: {input_token}, Output: {output_token}")

        if not llm_res:
            log.warning("LLM response nothing, try again")
            return

        # Push response from LLM, could be tool_calls or just text
        self.history_message.append(llm_res)
        if llm_res.content and not llm_res.toolcalls:
            console.print("\n 🤖 [bold bright_yellow]Assistant[/bold bright_yellow]:\n")
            console.print(Markdown(llm_res.content))
            console.print("\n")
            return

        tool_call_results: list[CallToolResultWithID] = []
        for tool_call in llm_res.toolcalls:
            id = tool_call.id
            name = tool_call.name
            arguments = tool_call.arguments
            server_name, tool_name = name.split(COMMON_SEPERATOR)
            if not server_name or not tool_name:
                raise ValueError(f"Invalid tool name format: {name}")

            server = self.servers.get(server_name, None)
            if not server:
                raise ValueError(f"Server not found: {server_name}")

            tool = next((
                tool for tool in self.tools if tool.name == name), None)
            tool_call_res: types.CallToolResult = await server.execute_tool(
                tool=tool,
                arguments=arguments
            )

            if tool_call_res.isError:
                log.warning(
                    f"Error executing tool: {tool_name}, error is: {tool_call_res.content}")

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
        self.history_message.append(GenericMsg(
            message_content=tool_call_results
        ))

        if len(tool_call_results) > 0:
            await self.run_promt(
                provider=provider,
                prompt=""
            )

    async def cleanup_servers(self) -> None:
        """Clean up all servers properly."""
        # cleanup must follow the FIFO: https://github.com/modelcontextprotocol/python-sdk/issues/577
        for name, server in reversed(list(self.servers.items())):
            log.info(f"Shutting down MCP server: [{name}]")
            await server.cleanup()

    def create_provider(self, base_url: str = None) -> Provider:
        if ":" not in self.model:
            raise ValueError("Invalid format! Expected format is 'a:b'")

        provider, model = self.model.split(":", 1)
        log.info(f"Model loaded: Provider: [{provider}] Model: [{model}]")

        if provider == "openai":
            api_key = os.environ.get('OPENAI_API_KEY', '')
            if api_key == "":
                raise ValueError(
                    'Environment variable OPENAI_API_KEY not found or its value is empty.')
            
            return Openai(model=model, base_url=base_url)  # TODO
        
        elif provider == "deepseek":
            api_key = os.environ.get('OPENAI_API_KEY', '')
            if api_key == "":
                raise ValueError(
                    'Environment variable OPENAI_API_KEY not found or its value is empty.')
            
            return Deepseek(model=model, base_url=base_url)  # TODO
        
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
            return Ollama(model=model)

        elif provider == "gemini":
            api_key = os.environ.get('GEMINI_API_KEY', '')
            if api_key == "":
                raise ValueError(
                    'Environment variable GEMINI_API_KEY not found or its value is empty.')
            
            return Gemini(model=model)
        
        raise ValueError(
            "Unsupport provider: {provider}, should be in ['openai', 'azure', 'ollama', 'deepseek']")

    async def run_mcp_host(self):
        # use register to supply the provider TODO
        provider = self.create_provider(base_url=self.openai_url)

        mcpserver_confs: dict[str, StdioServerParameters] = load_mcp_config(
            server_conf_path=self.server_conf_path)

        self.servers = {
            name: Server(name, srv_config)
            for name, srv_config in mcpserver_confs.items()
        }

        for name, server in self.servers.items():
            try:
                log.info(f"Initializing server... [{name}]")
                initialize_result: types.InitializeResult = await server.initialize(self.debug_model, provider, self.roots)
                log.info(f"Server connected: [{name}]")
                console.print(Markdown(format_server_card(initialize_result)))
                self.initialize_results[name] = initialize_result
            except Exception as e:
                await self.cleanup_servers()
                raise RuntimeError(
                    f"Failed to initialize server {name}") from e

        tools: list[types.Tool] = []
        for name, server in self.servers.items():
            if not server:
                raise RuntimeError(f"Server {name} not initialized")
            if self.initialize_results.get(name).capabilities.tools:
                tools_response: list[types.Tool] = await server.list_tools()
                tools.extend(tools_response)

        log.info(f"Tools loaded, total count: {len(tools)}")
        self.tools = tools
        
        # Treat resource_templates(not resources) as specific tools, similar to GET endpoints in a REST API. 
        resource_tools: list[types.Tool] = []
        for name, server in self.servers.items():
            if not server:
                raise RuntimeError(f"Server {name} not initialized")
            if self.initialize_results.get(name).capabilities.resources:
                try:
                    resource_templates: list[types.ResourceTemplate] = await server.list_resource_templates()
                    resource_tools.extend(generated_tools_from_resource_templates(name, resource_templates))
                except shared.exceptions.McpError as e:
                    log.info(f"Server {name} does not support resource templates: {e}")
                    continue

        if len(resource_tools) > 0:
            self.tools.extend(resource_tools)
            log.info(f"Resource tools generated, total count: {len(resource_tools)}")
            console.print(
                f"[green bold]💌 Extral tools from 'resource templates' generated, count: {len(resource_tools)}. you can check the defails by command: '/tools'[/green bold]")
            
        self.resource_tools = resource_tools

        resources: dict[str, list[str]] = defaultdict(list)
        for name, server in self.servers.items():
            if not server:
                raise RuntimeError(f"Server {name} not initialized")

            if self.initialize_results.get(name).capabilities.resources:
                for resource in await server.list_resources():
                    resources[str(resource.uri)].append(server.name)
        self.resources = resources
        log.info(f"Resources loaded, total count: {len(resources)}")

        prompts: list[types.Prompt] = []
        for name, server in self.servers.items():
            if not server:
                raise RuntimeError(f"Server {name} not initialized")

            if self.initialize_results.get(name).capabilities.prompts:
                for prompt in await server.list_prompts():
                    prompts.append(prompt)
        self.prompts = prompts
        log.info(f"Prompts loaded, total count: {len(prompts)}")

        try:
            while True:
                try:
                    self.history_message = prune_messages(self.history_message, self.message_window, True if self.sys_prompt else False)
                    user_input = console.input(
                        "[bold magenta]Enter your prompt (Type /help for commands, Ctrl+C to quit)[/bold magenta]\n")
                    
                    print(f"{PREV_LINE}{PREV_LINE}{CLEAR_RIGHT}")
                    if not user_input:
                        continue

                    console.print(f" 🤠 [bold bright_yellow]You[/bold bright_yellow]: [bold bright_white]{user_input}[/bold bright_white]")
                    if user_input in ["quit", "exit"]:
                        console.print("\nGoodbye")
                        break
                    
                    state, prompt_messages = await self.handle_slash_command(prompt=user_input)
                    if state:
                        continue

                    await self.run_promt(
                        provider=provider,
                        prompt=user_input,
                        messages=prompt_messages
                    )

                except KeyboardInterrupt:
                    console.print("\n[magenta]Goodbye![/magenta]")
                    break
        except Exception:
            raise
        finally:
            await self.cleanup_servers()


async def main() -> None:
    """Initialize and run the chat session."""
    parser = argparse.ArgumentParser(prog='mcpclihost', description="")
    parser.add_argument('--config', required=False,
                        help="config file (default is $HOME/mcp.json)")
    parser.add_argument('--message-window', required=False, type=int,
                        default=10, help="number of messages to keep in context")
    parser.add_argument('-m', '--model', required=True,
                        help="model to use (format: provider:model, e.g. azure:gpt-4-0613 or ollama:qwen2.5:3b)")
    parser.add_argument('--debug', required=False,
                        action="store_true", help="enable debug logging")
    parser.add_argument('--base-url', required=False,
                        help="base URL for OpenAI API (defaults to api.openai.com)")
    parser.add_argument('--roots', required=False, nargs='*',
                        help="clients to expose filesystem “roots” to servers")
    parser.add_argument('--sys-prompt', required=False,
                        help="system prompts to expose to clients")
    args = parser.parse_args()

    rich_handler = RichHandler(show_path=False, show_time=False, omit_repeated_times=False, show_level=True, highlighter=NullHighlighter(), rich_tracebacks=True)
    if args.debug:
        FORMAT = "%(asctime)s <%(filename)s:%(lineno)d> %(message)s"
        rich_handler.setFormatter(logging.Formatter(FORMAT))
        log.addHandler(rich_handler)
        log.setLevel(logging.DEBUG)
    else:
        FORMAT = "%(asctime)s %(message)s"
        rich_handler.setFormatter(logging.Formatter(FORMAT))
        log.addHandler(rich_handler)
        log.setLevel(logging.INFO)
    
    try:
        chat_session = ChatSession(
            model=args.model,
            server_conf_path=args.config,
            openai_url=args.base_url,
            message_window=args.message_window,
            debug_model=args.debug,
            roots=args.roots,
            sys_prompt=args.sys_prompt)
        
        await chat_session.run_mcp_host()
    except Exception as e:
        traceback.print_exception(e)
        log.error(f"{e}")
        log.exception(e)
        parser.print_help()

def run():
    asyncio.run(main())

if __name__ == '__main__':
    asyncio.run(main())