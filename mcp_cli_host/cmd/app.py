from mcp_cli_host.llm.azure.provider import Azure
from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.llm.models import GenericMsg, Role, CallToolResultWithID, TextContent
from mcp_cli_host.cmd.mcp import load_mcp_config, Server
from mcp import types, StdioServerParameters
import json
import logging
import asyncio

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def run_promt(provider: Provider,
                    prompt: str,
                    messages: list[GenericMsg],
                    tools: list[types.Tool],
                    servers: dict[str, Server]):

    if prompt != "":
        message = {
            "role": Role.USER.value,
            "content": prompt
        }

        # Push promot from user
        messages.append(
            GenericMsg(message_content=json.dumps(message))
        )

    llm_res: GenericMsg = provider.completions_create(
        prompt=prompt,
        messages=messages,
        tools=tools,
    )
    if not llm_res:
        return
    
    # Push response from LLM, could be tool_calls or just text
    messages.append(llm_res)
    if llm_res.content:
        print("Asistant--->: %s", llm_res.content)
        return

    tool_call_results: list[CallToolResultWithID] = []
    for tool_call in llm_res.toolcalls:
        id = tool_call.id
        name = tool_call.name
        arguments = tool_call.arguments

        server_name, tool_name = name.split("__")
        if not server_name or not tool_name:
            raise ValueError(f"Invalid tool name format: {name}")

        server = servers.get(server_name, None)
        if not server:
            raise ValueError(f"Server not found: {server_name}")

        tool_call_res: types.CallToolResult = await server.execute_tool(
            tool_name=tool_name,
            arguments=arguments
        )

        if tool_call_res.isError:
            logger.warning(
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
        await run_promt(
            provider=provider,
            prompt="",
            messages=messages,
            tools=tools,
            servers=servers
        )

    return


async def cleanup_servers(servers: dict[str, Server]) -> None:
    """Clean up all servers properly."""
    cleanup_tasks = [
        asyncio.create_task(server.cleanup()) for _, server in servers.items()
    ]
    if cleanup_tasks:
        try:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        except Exception as e:
            logging.warning(f"Warning during final cleanup: {e}")


async def run_mcp_host(server_conf_path: str, prompt: str):
    # use register to supply the provider TODO
    provider = Azure(model="gpt-4-0613")

    mcpserver_confs: dict[str, StdioServerParameters] = load_mcp_config(
        server_conf_path=server_conf_path)

    servers = {
        name: Server(name, srv_config)
        for name, srv_config in mcpserver_confs.items()
    }

    for name, server in servers.items():
        try:
            await server.initialize()
        except Exception as e:
            logging.error(f"Failed to initialize server {name}, get exception: {e}")
            await cleanup_servers(servers)
            return
        
    tools: list[types.Tool] = []
    for name, server in servers.items():
        if not server:
            raise RuntimeError(f"Server {name} not initialized")

        tools_response: list[types.Tool] = await server.list_tools()
        tools.extend(tools_response)

    history_message: list[GenericMsg] = []
    try:
        while True:
            try:
                user_input = input("You: ").strip().lower()
                if user_input in ["quit", "exit"]:
                    logging.info("\nExiting...")
                    break
                await run_promt(
                    provider=provider,
                    prompt=prompt,
                    messages=history_message,
                    tools=tools,
                    servers=servers
                )

            except KeyboardInterrupt:
                logging.info("\nExiting...")
                break

    finally:
        await cleanup_servers(servers)


async def main() -> None:
    """Initialize and run the chat session."""
    await run_mcp_host(server_conf_path=None, prompt="show pet with id 2")

if __name__ == '__main__':
    asyncio.run(main())
