"""
HORIZON LLM 客户端 — 多模型智能路由
"""
import asyncio, json, re
import aiohttp
from ..config import HORIZON, MODELS


def select_model(has_image: bool = False, is_compression: bool = False) -> str:
    if is_compression:
        return MODELS["compressor"]
    if has_image:
        return MODELS["vision"]
    return MODELS["default"]


def clean_response(content: str, model: str) -> str:
    """清理模型输出: MiniMax thinking格式 + 残留Markdown符号"""
    # MiniMax thinking/response 格式
    if model == MODELS["vision"] or "minimax" in model.lower():
        if " response" in content:
            parts = content.rsplit(" response", 1)
            if len(parts) > 1 and parts[1].strip():
                content = parts[1]

    # 清理残留 Markdown 符号 (DeepSeek 有时忽略 prompt 约束)
    content = re.sub(r"\*\*(.+?)\*\*", r"\1", content)     # **粗体**
    content = re.sub(r"\*(.+?)\*", r"\1", content)          # *斜体*
    content = re.sub(r"`{1,3}[^`]*`{1,3}", "", content)    # `代码`
    content = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)  # # 标题
    content = re.sub(r"^>\s+", "", content, flags=re.MULTILINE)       # > 引用
    content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)       # [文字](url)

    return content.strip()


class LLMClient:
    """HORIZON API 客户端 (OpenAI 兼容)"""

    def __init__(self):
        self.base_url = f"{HORIZON['base_url']}/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {HORIZON['auth_token']}",
            "Content-Type": "application/json",
        }
        self.timeout = aiohttp.ClientTimeout(total=HORIZON["timeout"])

    async def chat(
        self,
        model: str,
        messages: list[dict],
        system: str = "",
        max_tokens: int = None,
        temperature: float = None,
    ) -> str:
        """发送聊天请求"""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ] if system else messages,
            "max_tokens": max_tokens or HORIZON["max_tokens"],
            "temperature": temperature if temperature is not None else HORIZON["temperature"],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.base_url, headers=self.headers, json=payload,
                timeout=self.timeout,
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"LLM API error {resp.status}: {json.dumps(data, ensure_ascii=False)[:300]}")
                content = data["choices"][0]["message"]["content"]
                return clean_response(content.strip(), model)

    async def chat_with_fallback(
        self,
        messages: list[dict],
        system: str = "",
        has_image: bool = False,
        is_compression: bool = False,
    ) -> str:
        """带自动回退的聊天"""
        model = select_model(has_image, is_compression)
        try:
            return await self.chat(model, messages, system)
        except Exception as e:
            print(f"[LLM] {model} 失败: {e}, 回退到 {MODELS['fallback']}")
            if is_compression:
                return ""
            try:
                return await self.chat(MODELS["fallback"], messages, system)
            except Exception as e2:
                print(f"[LLM] 回退也失败: {e2}")
                return "抱歉，我暂时无法处理你的消息，请稍后再试~ 🏀"


# 全局单例
_llm_client: LLMClient = None

def get_llm() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client