from mcp_cli_host.llm.models import GenericMsg, ToolCall
from typing import Union
import json

class ollamaMsg(GenericMsg):
    @property
    def content(self) -> Union[str, None]:
        msg_obj = json.loads(self.message_content)

        return msg_obj["content"]
    
    @property
    def toolcalls(self) -> list[ToolCall]:
        msg_obj = json.loads(self.message_content)
        tool_calls: list[ToolCall] = []

        for call in msg_obj.get("tool_calls", []):
            call_obj = ToolCall(name=call["function"]["name"],
                                arguments=call["function"]["arguments"])
            
            tool_calls.append(call_obj)

        return tool_calls

    @property  
    def usage(self) -> list[int]:
        return [self.token_usage.prompt_tokens, self.token_usage.completion_tokens] if self.token_usage else None
