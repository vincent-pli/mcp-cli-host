from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.llm.models import GenericMsg, Role
from mcp_cli_host.llm.azure.models import azureMsg
from openai import OpenAI, RateLimitError
from typing import Optional, Union
import json
import logging
from mcp import types

log = logging.getLogger("mcp_cli_host")


class Openai(Provider):
    __name = "openai"

    def __init__(self, model: str, base_url: str = None):
        super(Openai, self).__init__(model)

        self.client = OpenAI(
            base_url=base_url
        )

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
                            "content": res.content,
                            "tool_call_id": res.tool_call_id
                        }
                    )
            else:
                openai_msgs.append(msg.to_json())

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=openai_msgs,
                tools=opeanpi_tools,
                tool_choice="auto"
            )

        except RateLimitError as e:
            log.warning(f"OpenAI API request exceeded rate limit, please try later: {e}")
        except Exception as e:
            if "maximum context length" in str(e):
                log.warning(f"llm hit its maximum context length: {e}")
            else:
                raise e

        return azureMsg(message_content=json.dumps(completion.choices[0].message.to_dict()),
                        token_usage=completion.usage) if completion else None
