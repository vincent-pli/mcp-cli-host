import asyncio
import argparse
from rich.logging import RichHandler
from rich.highlighter import NullHighlighter
import logging
from mcp_cli_host.cmd.app import ChatSession

log = logging.getLogger("mcp_cli_host")

async def main() -> None:
    """Initialize and run the chat session."""
    parser = argparse.ArgumentParser(prog='mcphost', description="")
    parser.add_argument('--config', required=False,
                        help="config file (default is $HOME/mcp.json)")
    parser.add_argument('--message-window', required=False, type=int,
                        default=10, help="number of messages to keep in context")
    parser.add_argument('-m', '--model', required=True,
                        help="model to use (format: provider:model, e.g. azure:gpt-4-0613 or ollama:qwen2.5:3b)")
    parser.add_argument('--debug', required=False,
                        action="store_true", help="enable debug logging")
    parser.add_argument('--openai-url', required=False,
                        help="base URL for OpenAI API (defaults to api.openai.com)")
    args = parser.parse_args()

    rich_handler = RichHandler(show_path=False, show_time=False, omit_repeated_times=False, show_level=True, highlighter=NullHighlighter(), rich_tracebacks=True)
    if args.debug:
        FORMAT = "%(asctime)s <%(filename)s:%(lineno)d> %(message)s"
        rich_handler.setFormatter(logging.Formatter(FORMAT))
        log.addHandler(rich_handler)
        log.setLevel(logging.DEBUG)
    else:
        FORMAT = "%(asctime)s %(message)s"
        rich_handler.setFormatter(logging.Formatter(FORMAT))
        log.addHandler(rich_handler)
        log.setLevel(logging.INFO)
    
    try:
        chat_session = ChatSession(
            model=args.model,
            server_conf_path=args.config,
            openai_url=args.openai_url,
            message_window=args.message_window,
            debug_model=args.debug)
        
        await chat_session.run_mcp_host()
    except Exception as e:
        log.error(f"{e}")
        log.exception(e)
        parser.print_help()


if __name__ == '__main__':
    asyncio.run(main())
