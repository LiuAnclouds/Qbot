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
        return "你是一个友好的QQ Bot AI助手，回复简洁自然，像真人聊天，不要用Markdown格式。"

    content = agent_md.read_text(encoding="utf-8")
    # 去掉 YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        content = parts[2] if len(parts) > 2 else content

    return content.strip()