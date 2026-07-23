"""
QBot 全局配置 — 所有配置集中管理
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

QQ_BOT = {
    "app_id": os.environ.get("QBOT_APP_ID", "1903593494"),
    "app_secret": os.environ.get("QBOT_APP_SECRET", "ppqrtvy15AFLRYfnv4EOZkw8LYm0FUk1"),
    "api_host": "https://api.sgroup.qq.com",
    "gateway_host": "api.sgroup.qq.com",
    "auth_url": "https://bots.qq.com/app/getAppAccessToken",
}

HORIZON = {
    "base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://llmapi.horizon.auto"),
    "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN", "eVSJLuMvTKkv5col"),
    "timeout": 120,
    "max_tokens": 2048,
    "temperature": 0.7,
}

MODELS = {
    "default": "HORIZON-DeepSeek-Pro",
    "vision": "HORIZON-MiniMax",
    "fallback": "HORIZON-GLM",
    "compressor": "HORIZON-DeepSeek-Pro",
}

CONTEXT = {
    "max_chars": 1_000_000,
    "max_turns": 50,
    "compress_threshold": 800_000,
    "compress_target": 200_000,
}

ALLOWED_GROUPS: list[str] = []

for d in [DATA_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def load_agent_prompt() -> str:
    agent_md = BASE_DIR / "AGENT.md"
    if not agent_md.exists():
        return "你是一个友好的QQ Bot AI助手。"
    content = agent_md.read_text(encoding="utf-8")
    if content.startswith("---"):
        parts = content.split("---", 2)
        content = parts[2] if len(parts) > 2 else content
    return f"""你是一个通过QQ接入的AI助手。请严格按照以下人设和行为准则行动：

{content.strip()}

【回复格式硬性规则 — 必须严格遵守】
你是在QQ上聊天，不是写文档！以下格式符号绝对禁止出现：
- 禁止 ** 加粗 — 用「」代替强调
- 禁止 * 斜体
- 禁止 # 标题
- 禁止 - 或 1. 列表 — 用逗号或换行分隔
- 禁止 ` 代码块
- 禁止 > 引用
- 禁止 [链接](url) 格式 — 直接贴链接文本
- 禁止任何 Markdown 语法

正确示例：
  "坤坤的篮球打得真不错，上次比赛我看他连进三个三分球"
  "你可以试试这个方法：先打开设置，然后找到隐私选项，关掉那个开关就行"

错误示例（绝对禁止）：
  "**坤坤**的篮球打得真不错"
  "你可以试试：1. 打开设置 2. 找到隐私 3. 关闭开关"

回复长度：群聊200字内，私聊500字内。像真人聊天一样自然说话，不要结构化，不要分段标题。"""