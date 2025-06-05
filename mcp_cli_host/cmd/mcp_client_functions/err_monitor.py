from anyio.streams.memory import MemoryObjectReceiveStream
from typing_extensions import Self
from types import TracebackType
import anyio
import logging

log = logging.getLogger("mcp_cli_host")

class ERRMonitor:
    def __init__(
        self,
        read_stderr: MemoryObjectReceiveStream,
    ):
        self.read_stderr = read_stderr

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._monitor_server_stderr)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        if self._task_group:
            self._task_group.cancel_scope.cancel()
            return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        return None

    async def _monitor_server_stderr(self):
        async with (
            self.read_stderr,
        ):
            async for message in self.read_stderr:
                log.debug(
                    "👻 Received err from server: %s", message.decode() if isinstance(message, bytes) else message)
