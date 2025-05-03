CLEAR_RIGHT = "\033[K"
PREV_LINE = "\033[F"

MARKDOWN = """
# Available Commands
The following commands are available:
- **/help**: Show this help message
- **/tools**: List all available tools
- **/servers**: List configured MCP servers
- **/history**: Display conversation history
- **/quit**: Exit the application

You can also press Ctrl+C at any time to quit.

## Available Models
Specify models using the --model or -m flag:
- **Azure Openai**: `azure:modelname`
- **Ollama Models**: `ollama:modelname`

Examples:
mcphost -m azure:gpt-4-0613
mcphost -m ollama:qwen2.5:3b
"""