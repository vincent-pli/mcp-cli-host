from mcp.shared.session import RequestResponder
from mcp import types
import logging

log = logging.getLogger("mcp_cli_host")

async def message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult]
    | types.ServerNotification
    | Exception
    | str
) -> None:
    if isinstance(message, Exception):
        log.error("Error: %s", message)
        return
    if isinstance(message, types.ServerNotification):
        if isinstance(message.root, types.LoggingMessageNotification):
            message_obj: types.LoggingMessageNotification = message.root
            log.debug(
                "📩 Received log notification message from server: %s", message_obj.params.data)