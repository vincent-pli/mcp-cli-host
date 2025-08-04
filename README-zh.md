# MCPCLIHost 🤖
一个 CLI 主机应用程序，可以通过模型上下文协议 (MCP) 使大型语言模型 (LLM) 与外部工具进行交互。目前支持 Openai、Azure Openai、Deepseek 和 Ollama 模型。

## 特性 ✨
- 与多个 LLM 模型进行交互式对话
- 支持多个并发的 MCP 服务器
- 动态工具发现和集成
- 可配置的 MCP 服务器位置和参数
- 在模型类型之间提供一致的命令接口
- 可配置的消息历史窗口，用于上下文管理
- 监控和跟踪来自server端的错误
- 支持sampling, Roots, Elicitation, Resources, Prompts
- 支持对话中去掉某个tool
- 当mcp server链接成功后，展示其信息card

## 最新更新 💌
- [2025-07-18] 支持Streamable HTTP mcp server，Oauth还不支持
- [2025-07-02] 支持Elicitation
- [2025-06-27] 使用Server的Prompts: [Link](./docs/zh/prompts_usage.md)
- [2025-06-20] 针对Server的Resource templates的实现和想法: [Link](./docs/zh/resource_templates_implements.md)

## 环境设置 🔧
1. 对于 Openai 和 Deepseek:
```bash
export OPENAI_API_KEY='your-api-key'
```
默认情况下，Openai 的 `base_url` 是 "https://api.openai.com/v1"
对于 deepseek，它是 "https://api.deepseek.com"，你可以通过 `--base-url` 来改变它
2. 对于 Ollama，需要先设置：
- 从 https://ollama.ai 安装 Ollama
- 拉取你需要的模型：
```bash
ollama pull mistral
```
- 确保 Ollama 在运行：
```bash
ollama serve
```
3. 对于 Azure Openai：
```bash
export AZURE_OPENAI_DEPLOYMENT='your-azure-deployment'
export AZURE_OPENAI_API_KEY='your-azure-openai-api-key'
export AZURE_OPENAI_API_VERSION='your-azure-openai-api-version'
export AZURE_OPENAI_ENDPOINT='your-azure-openai-endpoint'
```
4. 对于 Google Gemini
```bash
export GEMINI_API_KEY='your-gemini-api-token'
```
## 安装 📦
```bash
pip install mcp-cli-host
```
## 配置 ⚙️
MCPCLIHost 将自动在 `~/.mcp.json` 中找到配置文件。你也可以使用 `--config` 标志指定自定义位置：

### STDIO mcp server 例子
```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": [
        "mcp-server-sqlite",
        "--db-path",
        "/tmp/foo.db"
      ]
    },
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/tmp"
      ]
    }
  }
}
```
每个 MCP 服务器条目需要：
- `command`：要运行的命令（例如，`uvx`，`npx`） 
- `args`：命令的参数数组：
  - 对于 SQLite 服务器：`mcp-server-sqlite` 并指定数据库路径
  - 对于文件系统服务器：`@modelcontextprotocol/server-filesystem` 并指定目录路径

### 远端mcp server(仅支持Streamable HTTP)例子
```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {"Authorization": "Bearer <your PAT>"}
    }
  }
}
```

## 使用 🚀
MCPCLIHost 是一个 CLI 工具，允许你通过统一的接口与各种 AI 模型进行交互。它支持通过 MCP 服务器的各种工具。
### 可用模型
模型可以使用 `--model` （`-m`）标志指定：
- Deepseek：`deepseek:deepseek-chat`
- OpenAI：`openai:gpt-4`
- Ollama 模型：`ollama:modelname`
- Azure Openai：`azure:gpt-4-0613`
- Gemini: `gemini:gemini-2.5-flash`
### 示例
```bash
# 使用带 Qwen 模型的 Ollama
mcphost -m ollama:qwen2.5:3b
# 使用 Deepseek
mcphost -m deepseek:deepseek-chat --sys-prompt 你是一个有点俏皮的助手，请用可爱的语气回答问题
```
### 标志
- `--config string`：配置文件位置（默认为 $HOME/mcp.json）
- `--debug`：启用调试日志
- `--message-window int`：在上下文中保存消息的数量（默认：10）
- `-m, --model string`：使用的模型（格式：提供者:模型）（默认 "anthropic:claude-3-5-sonnet-latest"）
- `--base-url string`：OpenAI API 的基础 URL（默认为 api.openai.com）
- `--roots string`:  MCP 客户端提供给服务端：filesystem “roots”
- `--sys-prompt string`: System prompt

### 交互式命令
在聊天时，你可以使用：
- `/help`：显示可用命令
- `/tools`：列出所有可用工具
- `/exclude_tool tool_name`: 在对话中去掉某个tool
- `/resources`: 列出所有resource
- `/get_resource`: 使用URI获取某个resource, 例如: /get_resource resource_uri
- `/prompts`: 获取所有的prompt
- `/get_prompt`: 使用名字，获取某一prompt, 例如: /get_prompt prompt_name
- `/servers`：列出配置的 MCP 服务器
- `/history`：显示对话历史
- `quit`：任何时候都可以退出

## MCP 服务器兼容性 🔌
MCPHost 可以与任何符合 MCP 的服务器一起工作。示例和参考实现，请参阅[MCP 服务器库](https://github.com/modelcontextprotocol/servers)。

## 已知问题：🐛
- 在采样(Sampling)和启发(Elicitation)场景下，当输入"Ctrl+c"时，进程会崩溃并出现类似asyncio.exceptions.CancelledError的错误，该问题将在后续版本中修复。

## 许可证 📄
本项目根据 Apache 2.0 许可证发行 - 请参阅[LICENSE](LICENSE)文件以获得详细信息。