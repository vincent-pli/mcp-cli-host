from pydantic import BaseModel
from typing import Literal
from enum import Enum
from typing import Union, Any, Optional
from abc import ABC
import json
from mcp import types

class Role(Enum):
    USER = 'user'
    ASSISTANT = 'assistant'
    TOOL = 'tool'
    SYSTEM = 'system'

class ToolCall(BaseModel):
    id: Optional[str] = None
    name: str
    arguments: dict[str, Any]

class TextContent(BaseModel):
    type: str
    text: str

class CallToolResultWithID(BaseModel):
    tool_call_id: Optional[str] = None
    name: str
    content: list[TextContent]
    isError: bool = False

class GenericMsg(BaseModel, ABC):
    # json str, a whole message responsed by llm
    message_content: Union[str, list[CallToolResultWithID]]
    token_usage: Optional[Any] = None

    @property
    def content(self) -> str:
        return self.message_content
    
    @property
    def toolcalls(self) -> list[ToolCall]:
        pass

    @property
    def usage(self) -> list[int]:
        pass
    
    def to_json(self):
        return json.loads(self.message_content)

    def is_tool_res(self):
        return not isinstance(self.message_content, str)




if __name__ == '__main__':
    pass