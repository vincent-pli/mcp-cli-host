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

def encode_uri_template(template: str) -> str:
    """
    make URI template to pattern [a-zA-Z0-9_-] type
    for example: 
        "user/{id}/detail" → "user_7bid_7d_detail"
    """
    # Step 1: transfer {} to _7B_ and _7D_
    encoded = template.replace("{", "_7B_").replace("}", "_7D_")
    # Step 2: encode other charactor（ie. / → _2F_）
    encoded = re.sub(r'([^a-zA-Z0-9_-])', 
                    lambda m: f"_{ord(m.group(1)):02X}_", 
                    encoded)
    return encoded

def decode_uri_template(encoded: str) -> str:
    """
    make encoded string to original URI template
    for example: 
        "user_7Bid_7D_detail" → "user/{id}/detail"
    """
    decoded = encoded.replace("_7B_", "{").replace("_7D_", "}")
    decoded = re.sub(r'_([0-9A-F]{2})_', 
                    lambda m: chr(int(m.group(1), 16)), 
                    decoded)
    return decoded

def generated_tools_from_resource_templates(
    server_name: str,
    resource_templates: list[types.ResourceTemplate]
) -> list[types.Tool]:
    """Generate tools from resource templates."""
    tools: list[types.Tool] = []
    for template in resource_templates:
        tools.append(
            types.Tool(
                name=server_name + COMMON_SEPERATOR + PREFIX_RESOURCE_TOOL + encode_uri_template(template.uriTemplate),
                description=template.description,
                inputSchema=build_input_schema(
                    original_uri_template=template.uriTemplate,
                    properties=extract_variables_from_uri_template(
                        template.uriTemplate)
                )
            )
        )

    return tools
