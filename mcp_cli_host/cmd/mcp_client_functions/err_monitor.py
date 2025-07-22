from anyio.streams.memory import MemoryObjectReceiveStream
from contextlib import asynccontextmanager
import anyio
import logging

log = logging.getLogger("mcp_cli_host")

async def _monitor_server_stderr(read_stderr: MemoryObjectReceiveStream,):
    async for message in read_stderr:
        log.debug(
            "👻 Received err from server: %s", message.decode() if isinstance(message, bytes) else message)
            
@asynccontextmanager
async def err_monitor(
    read_stderr: MemoryObjectReceiveStream,
):
    async with anyio.create_task_group() as tg:
        try:
            tg.start_soon(_monitor_server_stderr, read_stderr)
            yield
        finally:
            tg.cancel_scope.cancel()