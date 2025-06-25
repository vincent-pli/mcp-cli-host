# Resources of MCP server

Actually I always confused with the `Resources`: if you want to support content retrival, why not just let tool to do such job, I mean supply tools for query related content(the offical said it' s just like `get` in rest API).

Then I found some difference:
from https://modelcontextprotocol.io/docs/concepts/tools:
"Tools are designed to be model-controlled, meaning that tools are exposed from servers to clients with the intention of the AI model being able to automatically invoke them (with a human in the loop to grant approval)."

And this is different to resources:
https://modelcontextprotocol.io/docs/concepts/resources:
"Resources are designed to be application-controlled, meaning that the client application can decide how and when they should be used. Different MCP clients may handle resources differently."

That's make sense, I can suppose people use `resources/list` to check what server offered and with `resources/read` to get what they interested: **not involve LLM**, right?

But what about `Resource Templates`, the URI template(file:///{path}, {scheme}://{host}/api), it's most like the `Tools`, you just need fetch the uri with arguments(maybe by LLM).

So in `mcp-cli-host`, we transfer `Resource Templates` to specific tools, then you can engage then with LLM, like this:
![snapshot](./images/resource_tools.png)