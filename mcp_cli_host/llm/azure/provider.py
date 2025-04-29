from mcp_cli_host.llm.base_provider import Provider
from mcp_cli_host.llm.models import GenericMsg, Role
from mcp_cli_host.llm.azure.models import azureMsg
import os
from openai import AzureOpenAI, RateLimitError
from typing import Optional, Union
import json
import logging
from mcp import types

logger = logging.getLogger(__name__)


class Azure(Provider):
    __name = "azure_openai"

    def __init__(self, model: str):
        super(Azure, self).__init__(model)

        self.client = AzureOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
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
            logger.warning(f"OpenAI API request exceeded rate limit, please try later: {e}")
        except Exception as e:
            if "maximum context length" in str(e):
                logger.warning(f"llm hit its maximum context length: {e}")
            else:
                raise

        return azureMsg(message_content=json.dumps(completion.choices[0].message.to_dict())) if completion else None
