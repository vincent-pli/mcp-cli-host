from mcp.shared.session import RequestResponder
from mcp import types
import logging
from rich.progress import Progress

log = logging.getLogger("mcp_cli_host")


class NotificationHandler:
    def __init__(self):
        self.current_task = None
        self.process = Progress()

    async def __call__(self,
                       message: RequestResponder[types.ServerRequest,
                                                 types.ClientResult]
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

            if isinstance(message.root, types.ProgressNotification):
                message_obj: types.ProgressNotification = message.root
                message = message_obj.params.message if message_obj.params.message else "Progressing..."
                self.process.start()
                if self.current_task is None:
                    self.current_task = self.process.add_task(
                        description=f"[green]{message}[/green]",
                        total=message_obj.params.total
                    )
                else:
                    self.process.update(self.current_task, completed=message_obj.params.progress, total=message_obj.params.total, description=f"[green]{message}[/green]")
                
                if message_obj.params.progress >= message_obj.params.total:
                    self.process.stop()
                    if self.current_task in self.process.task_ids:
                        self.process.remove_task(self.current_task)
                    self.current_task = None
