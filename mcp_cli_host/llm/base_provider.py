from abc import ABC, abstractmethod
import os
from openai import OpenAI, AzureOpenAI
from .models import GenericMsg
from typing import Union, Literal, Any, Optional
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
    def completions_create(self, prompt: str, messages: list[GenericMsg], tools: Optional[list[types.Tool]] = None) -> Union[GenericMsg, None]:
        ...


if __name__ == '__main__':
    # client = OpenAI()
    client = AzureOpenAI(
        azure_deployment="csg-gpt4",
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )

    response = client.chat.completions.create(
        model="gpt-4-0613",
        messages=[
            {"role": "developer", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
    )

    print(response)
