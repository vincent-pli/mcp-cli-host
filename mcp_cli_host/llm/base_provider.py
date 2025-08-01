from abc import ABC, abstractmethod
from .models import GenericMsg
from typing import Union, Optional
from mcp import types


class Provider(ABC):
    _name: str
    __client: any

    def __init__(self, model: str):
        self.model = model
        self.__client = None

    @classmethod
    def name(cls):
        return cls._name

    # Have to handle the differentiation for LLMs
    @abstractmethod
    def completions_create(self, prompt: str, messages: list[GenericMsg], tools: Optional[list[types.Tool]] = None, max_tokens: int = None) -> Union[GenericMsg, None]:
        ...

