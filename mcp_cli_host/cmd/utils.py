from mcp_cli_host.llm.models import GenericMsg
from mcp import types

CLEAR_RIGHT = "\033[K"
PREV_LINE = "\033[F"

MARKDOWN = """
# Available Commands
The following commands are available:
- **/help**: Show this help message
- **/tools**: List all available tools
- **/servers**: List configured MCP servers
- **/history**: Display conversation history
- **/quit**: Exit the application
- **/exclude_tool**: Exclude specific tool from the conversation, example: `/exclude_tool tool_name`

You can also press Ctrl+C at any time to quit.

## Available Models
Specify models using the --model or -m flag:
- **Azure Openai**: `azure:modelname`
- **Ollama Models**: `ollama:modelname`
- **Deepseek Models**: `deepseek:deepseek-chat`

Examples:   
mcpclihost -m azure:gpt-4-0613    
mcpclihost -m ollama:qwen2.5:3b    
mcpclihost -m deepseek:deepseek-chat    
"""

def prune_messages(messages: list[GenericMsg], message_window: int) -> list[GenericMsg]:
    if len(messages) <= message_window:
        return messages

    if not messages[0].toolcalls:
        return messages[1:]
    else:
        return messages[2:]

SERVER_CARD = """

---

**MCP Server Card**    
*Protocol Version*: {protocol_version}     
*Server Name*: {name}    
*Version*: {version}   
*Capabilities*:
- {tool_enable} Tools
- {prompts_enable} Prompts
- {resources_enable} Rsources
- {logging_enable} Logging   
---

"""

def format_server_card(initialize_result: types.InitializeResult) -> str:
    name = initialize_result.serverInfo.name
    version = initialize_result.serverInfo.version
    protocol_version = initialize_result.protocolVersion

    tool_enable = "✅" if initialize_result.capabilities.tools else "🚫"
    prompts_enable = "✅" if initialize_result.capabilities.prompts else "🚫"
    resources_enable = "✅" if initialize_result.capabilities.resources else "🚫"
    logging_enable = "✅" if initialize_result.capabilities.logging else "🚫"

    return SERVER_CARD.format(
        name=name,
        version=version,
        tool_enable=tool_enable,
        prompts_enable=prompts_enable,
        resources_enable=resources_enable,
        logging_enable=logging_enable,
        protocol_version=protocol_version,
    )




