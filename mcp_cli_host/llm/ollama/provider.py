from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.llm.models import GenericMsg, Role, TextContent
from mcp_cli_host.llm.ollama.models import ollamaMsg
import os
from openai import AzureOpenAI, RateLimitError
from typing import Optional, Union
import json
import logging
from mcp import types
from ollama import Client
from ollama import ChatResponse



log = logging.getLogger("mcp_cli_host")

def handle_content_ollama(contents: list[TextContent]) -> str:
    res = ""
    for content in contents:
        res += content.text + "\n"

    return res

class Ollama(Provider):
    _name = "ollama"

    def __init__(self, model: str):
        super(Ollama, self).__init__(model)

        # Support 'host', 'header' .etc to handle the remote ollama server TODO
        self.client = Client()

    def completions_create(self, prompt: str, messages: list[GenericMsg], tools: Optional[list[types.Tool]] = None) -> Union[GenericMsg, None]:
        opeanpi_tools = []
        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                }
            }
            opeanpi_tools.append(openai_tool)

        openai_msgs = []
        for msg in messages:
            # have no idea how message looks like with role=tool, follow the discussion below:
            # https://learn.microsoft.com/en-us/answers/questions/1726523/missing-parameter-tool-call-id-messages-with-role
            if msg.is_tool_res():
                for res in msg.message_content:
                    openai_msgs.append(
                        {
                            "role": Role.TOOL.value,
                            "name": res.name,
                            "content": handle_content_ollama(res.content),
                            "tool_call_id": res.tool_call_id
                        }
                    )
            else:
                openai_msgs.append(msg.to_json())

        try:
            completion = self.client.chat(
                model=self.model,
                messages=openai_msgs,
                tools=opeanpi_tools
            )

        except RateLimitError as e:
            log.warning(f"OpenAI API request exceeded rate limit, please try later: {e}")
        except Exception as e:
            if "maximum context length" in str(e):
                log.warning(f"llm hit its maximum context length: {e}")
            else:
                raise e

        return ollamaMsg(message_content=json.dumps(completion.message.model_dump()),
                        token_usage=None) if completion else None
