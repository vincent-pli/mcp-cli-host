from mcp_cli_host.llm.base_provider import Provider
from mcp.shared.context import RequestContext
from mcp import ClientSession, types
from typing import Any
import json
from rich.console import Console
from mcp_cli_host.cmd.utils import CLEAR_RIGHT, PREV_LINE
from mcp_cli_host.llm.models import GenericMsg, Role
import logging

console = Console()
log = logging.getLogger("mcp_cli_host")

class SamplingCallback:
    def __init__(self, provider: Provider):
        self.provider = provider

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        while True:
            try:
                messages_rec = json.dumps(
                    [msg.model_dump() for msg in params.messages], indent=2, ensure_ascii=False)
                user_confirmation = console.input(
                    f"[bold magenta]Received sampling request from Server (Type 'yes' for continue, 'no' for stop):[/bold magenta]\n[green]{messages_rec}\n[/green]The request will cost [bold red]{params.maxTokens}[/bold red] tokens (yes/no): ")

                print(f"{PREV_LINE}{PREV_LINE}{CLEAR_RIGHT}")
                if not user_confirmation:
                    continue

                if user_confirmation != "yes" and user_confirmation != "no":
                    continue

                console.print(
                    f" 🤠 [bold bright_yellow]You[/bold bright_yellow]: [bold bright_white]{user_confirmation}[/bold bright_white]")

                if user_confirmation == "yes":
                    messages: list[GenericMsg] = []
                    system_message = {
                        "role": Role.SYSTEM.value,
                        "content": params.systemPrompt
                    }

                    messages.append(GenericMsg(
                        message_content=json.dumps(system_message)
                    ))
                    # mcp SamplingMessage not match the message format of openai, meed transfer
                    # the message.content in openai is either a str or list[TextContent]
                    for msg in params.messages:
                        new_msg = {
                            "role": msg.role,
                            "content": [msg.content.model_dump()],
                        }
                        messages.append(GenericMsg(
                            message_content=json.dumps(new_msg))
                        )

                    with console.status("[bold bright_magenta]Thinking...[/bold bright_magenta]"):
                        try:
                            llm_res: GenericMsg = self.provider.completions_create(
                                prompt="",
                                messages=messages,
                                tools=[],
                                max_tokens=params.maxTokens,
                            )
                        except Exception:
                            raise

                    if llm_res and llm_res.usage:
                        input_token, output_token = llm_res.usage
                        log.info(
                            f"Token usage statistics: Input: {input_token}, Output: {output_token}")

                    if not llm_res:
                        log.warning("LLM response nothing, try again")
                        return types.ErrorData(
                            code=types.INVALID_REQUEST,
                            message="LLM response nothing, try again",
                        )

                    if llm_res.content and not llm_res.toolcalls:
                        return types.CreateMessageResult(
                            role="assistant",
                            content=types.TextContent(
                                type="text", text=llm_res.content),
                            model=self.provider.name(),
                            stopReason="endTurn",
                        )
                else:
                    console.print(" ❌, reject the request ")
                    return types.ErrorData(
                        code=types.INVALID_REQUEST,
                        message="User prevent the request",
                    )

            except KeyboardInterrupt:
                console.print("\n[magenta]Goodbye![/magenta]")
                break
            except Exception:
                raise