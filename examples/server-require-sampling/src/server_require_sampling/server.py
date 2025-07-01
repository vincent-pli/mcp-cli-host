import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
import os
from server_require_sampling.utils import file_url_to_path
from pathlib import Path
import time


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
        system_prompt="You are an excellent storyteller, known for your wit and humor. Craft a story based on the user's request, keeping it under 300 words."
    )

    return [value.content]


async def create_file_by_roots(
    file_name: str,
    content: str,
    server: Server
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    ctx = server.request_context
    value: types.ListRootsResult = await ctx.session.list_roots()

    await ctx.session.send_log_message(
        level="info",
        data=f"Received roots: {value.roots}",
        logger="notification_stream",
    )

    for i in range(11):
        await ctx.session.send_progress_notification(
            progress_token="file_creation_progress",
            progress=i / 10,
            total=1,
            message=f"Creating file {file_name} ({i * 10}% complete)",
        )
        time.sleep(1)

    base_path = file_url_to_path(value.roots[0].uri)
    file_path = os.path.join(base_path, file_name)
    Path(base_path).mkdir(parents=True, exist_ok=True)

    with open(file_path, "w") as file:
        file.write(content)

    return [types.TextContent(type='text', text=f"File has been created successfully at: {file_path}")]


async def build_table_user_info(
    prompt: str,
    server: Server
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    example_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "User Profile",
        "description": "A test schema combining all supported field types",
        "type": "object",
        "properties": {
            "userEmail": {
                "type": "string",
                "title": "Email Address",
                "description": "User's primary email address",
                "minLength": 5,
                "maxLength": 100,
                "format": "email"
            },
            "age": {
                "type": "integer",
                "title": "Age",
                "description": "User's age in years",
                "minimum": 18,
                "maximum": 120
            },
            "score": {
                "type": "number",
                "title": "Credit Score",
                "description": "User's credit rating",
                "minimum": 300,
                "maximum": 850
            },
            "isVerified": {
                "type": "boolean",
                "title": "Verified Status",
                "description": "Whether the user account is verified",
                "default": False
            },
            "membershipLevel": {
                "type": "string",
                "title": "Membership Level",
                "description": "User's subscription tier",
                "enum": ["basic", "pro", "enterprise"],
                "enumNames": ["Basic", "Professional", "Enterprise"]
            },
            "website": {
                "type": "string",
                "title": "Personal Website",
                "description": "URL of user's personal website",
                "format": "uri"
            },
            "birthDate": {
                "type": "string",
                "title": "Birth Date",
                "description": "User's date of birth",
                "format": "date"
            },
            "lastLogin": {
                "type": "string",
                "title": "Last Login",
                "description": "Timestamp of last login",
                "format": "date-time"
            },
            "username": {
                "type": "string",
                "title": "Username",
                "description": "User's display name",
                "minLength": 3,
                "maxLength": 20
            }
        },
        "required": ["userEmail", "username", "age"]
    }
    ctx = server.request_context
    result: types.ElicitResult = await ctx.session.elicit(
        message="Please provide your user information.",
        requestedSchema = example_schema)

    if result.action == "accept":
        return [types.TextContent(type='text', text=f"thanks for your information: {result.content}")] 
    if result.action == "decline":
        return [types.TextContent(type='text', text="user reject the information request")]
    if result.action == "cancel":
        return [types.TextContent(type='text', text="user cancel the information request, then get nothing")]

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
        if name != "fetch" and name != "create" and name != "build":
            raise ValueError(f"Unknown tool: {name}")
        if name == "fetch":
            if "prompt" not in arguments:
                raise ValueError("Missing required argument 'promot'")
            return await generate_story(arguments["prompt"], app)
        if name == "create":
            if "file_name" not in arguments and "content" not in arguments:
                raise ValueError(
                    "Missing required argument 'file_name'/'content'")
            return await create_file_by_roots(arguments["file_name"], arguments["content"], app)
        if name == "build":
            if "prompt" not in arguments:
                raise ValueError("Missing required argument 'promot'")
            return await build_table_user_info(arguments["prompt"], app)

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
            ),
            types.Tool(
                name="build",
                description="create a table with user information",
                inputSchema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "a short description about the user information",
                        }
                    },
                },
            ),
            types.Tool(
                name="create",
                description="create file with content from user",
                inputSchema={
                    "type": "object",
                    "required": ["file_name", "content"],
                    "properties": {
                        "file_name": {
                            "type": "string",
                            "description": "name of the file",
                        },
                        "content": {
                            "type": "string",
                            "description": "content of the file",
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
