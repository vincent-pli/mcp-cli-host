import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server


async def generate_story(
    prompt: str,
    server: Server
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    ctx = server.request_context
    value = await ctx.session.create_message(
        messages=[
            types.SamplingMessage(
                role="user", content=types.TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=300,
        system_prompt = "You are an excellent storyteller, known for your wit and humor. Craft a story based on the user's request, keeping it under 300 words."
    )

    
    return [value.content]

@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server("mcp-story-generator")

    @app.call_tool()
    async def fetch_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        if name != "fetch":
            raise ValueError(f"Unknown tool: {name}")
        if "prompt" not in arguments:
            raise ValueError("Missing required argument 'promot'")
        return await generate_story(arguments["prompt"], app)

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="fetch",
                description="create a shot story with user's promot",
                inputSchema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "a short description about the story",
                        }
                    },
                },
            )
        ]

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn

        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as (read_stream, write_stream):
                await app.run(
                    read_stream, write_stream, app.create_initialization_options()
                )

        anyio.run(arun)

    return 0
