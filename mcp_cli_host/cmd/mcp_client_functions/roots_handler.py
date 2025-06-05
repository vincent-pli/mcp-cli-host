from mcp.shared.context import RequestContext
from mcp import ClientSession, types
from typing import Any
from pydantic import FileUrl


class RootsCallback:
    def __init__(self, roots: list[str] = None):
        self.roots = roots

    async def __call__(self,
                       context: RequestContext["ClientSession", Any],
                       ) -> types.ListRootsResult | types.ErrorData:
        
        roots: list[types.Root] = []
        if self.roots:
            for index, root in enumerate(self.roots):
                roots.append(types.Root(
                    uri=FileUrl(root if root.startswith("file://") else "file://" + root),
                    name="workspace_" + str(index),
                ))

        return types.ListRootsResult(
            roots=roots
        )