from mcp_cli_host.llm.models import GenericMsg
from mcp import types
from uritemplate import URITemplate
from typing import List
import re

CLEAR_RIGHT = "\033[K"
PREV_LINE = "\033[F"

MARKDOWN = """
# Available Commands
The following commands are available:
- **/help**: Show this help message
- **/tools**: List all available tools
- **/exclude_tool**: Exclude specific tool from the conversation, example: `/exclude_tool tool_name`
- **/resources**: List all available resources
- **/get_resource**: Get specific resources by uri, example: `/get_resource resource_uri`
- **/prompts**: List all available prompts
- **/get_prompt**: Get specific prompt by name, example: `/get_prompt prompt_name`
- **/servers**: List configured MCP servers
- **/history**: Display conversation history
- **/quit**: Exit the application


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
PREFIX_RESOURCE_TOOL = "get_res_tmp_"
COMMON_SEPERATOR = "--"
URL_TEMPLATE_KEY = "url_template"

def prune_messages(messages: list[GenericMsg], message_window: int, has_sys_prompt: bool = False) -> list[GenericMsg]:
    if len(messages) <= message_window:
        return messages

    removed_count = len(messages) - message_window
    if has_sys_prompt:
        messages = messages[:1] + messages[1 + removed_count:]
    else:
        messages = messages[removed_count:]
    # After remove, If the first message is a toolcall result, we need to remove the next message as well
    if messages[0].is_tool_res():
        messages = messages[1:]

    return messages


SERVER_CARD = """

---

**MCP Server Card**    
*Protocol Version*: {protocol_version}     
*Server Name*: {name}    
*Version*: {version}   
*Capabilities*:
- {tool_enable} Tools
- {prompts_enable} Prompts
- {resources_enable} Resources
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


INPUT_SCHEMA_TEMPLATE = {
    "type": "object",
    "required": [],
    "properties": {
        "interval": {
            "type": "number",
            "description": "Interval between notifications in seconds",
        },
        "count": {
            "type": "number",
            "description": "Number of notifications to send",
        },
        "caller": {
            "type": "string",
            "description": (
                "Identifier of the caller to include in notifications"
            ),
        },
    },
},


def build_input_schema(
    original_uri_template: str,
    properties: list[str] | None = None
) -> dict[str, any]:
    """Build an input schema for a tool."""
    schema = {
        "type": "object",
        "required": [property for property in properties] if properties else [],
        "properties": {
            property: {
                "type": "string",
                "description": f"{property} in uri: {original_uri_template}"
            } for property in properties
        }
    }
    return schema


def extract_variables_from_uri_template(template: str) -> List[str]:
    """
    Extract all variable names from a URI template string

    Args:
        template: URI template string (e.g. "https://api.example.com/{user}/{resource_id}")

    Returns:
        List of variable names (e.g. ["user", "resource_id"])

    Raises:
        ValueError: If template format is invalid
    """
    try:
        parsed = URITemplate(template)
        return list(parsed.variable_names)
    except Exception as e:
        raise ValueError(f"Invalid URI template: {template}") from e 

def generated_tools_from_resource_templates(
    server_name: str,
    resource_templates: list[types.ResourceTemplate]
) -> list[types.Tool]:
    """Generate tools from resource templates."""
    tools: list[types.Tool] = []
    for index, template in enumerate(resource_templates):
        tools.append(
            types.Tool(
                name=server_name + COMMON_SEPERATOR + PREFIX_RESOURCE_TOOL + str(index),
                description=template.description if template.description else "Get resource from url:" + template.uriTemplate,
                inputSchema=build_input_schema(
                    original_uri_template=template.uriTemplate,
                    properties=extract_variables_from_uri_template(
                        template.uriTemplate)
                ),
                meta={URL_TEMPLATE_KEY: template.uriTemplate}, 
            )
        )

    return tools
