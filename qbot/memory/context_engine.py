"""
上下文引擎 & 用户画像 — QBot 记忆系统

参考 Hermes/Codex 的记忆系统设计:
  - 短期记忆: 滑动窗口上下文 (1M字符)
  - 长期记忆: 用户画像 (JSON持久化)
  - 自动压缩: 超阈值触发LLM摘要
  - 无效过滤: 灌水/表情/重复消息
"""
import json, re, time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from ..config import DATA_DIR, CONTEXT

CONV_DIR = DATA_DIR / "conversations"
PROFILE_DIR = DATA_DIR / "profiles"
ARCHIVE_DIR = DATA_DIR / "archives"

NOISE_PATTERNS = [
    re.compile(r"^[，。！？,.!?\s]*$"),
    re.compile(r"^[\U0001F000-\U0001FFFF\U00002600-\U000027BF]+$"),
    re.compile(r"^(?:哈哈|呵呵|嗯嗯|哦哦|666|ddd|草){1,10}$"),
    re.compile(r"^[\[\]【】\-\+=~`@#$%^&*()_]{1,20}$"),
]


@dataclass
class Message:
    role: str
    content: str
    username: str = ""
    user_id: str = ""
    timestamp: str = ""
    has_image: bool = False

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "Message": return cls(**d)
    def char_count(self) -> int: return len(self.content)


@dataclass
class Conversation:
    conv_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    total_chars: int = 0
    compress_count: int = 0

    def add(self, msg: Message):
        self.messages.append(msg)
        self.total_chars += msg.char_count()
        self.updated_at = datetime.now().isoformat()

    def needs_compress(self) -> bool:
        return self.total_chars > CONTEXT["compress_threshold"] or len(self.messages) > CONTEXT["max_turns"]

    def to_dict(self) -> dict:
        return {
            "conv_id": self.conv_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at, "updated_at": self.updated_at,
            "total_chars": self.total_chars, "compress_count": self.compress_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        conv = cls(conv_id=d["conv_id"], created_at=d.get("created_at", ""),
                   updated_at=d.get("updated_at", ""), total_chars=d.get("total_chars", 0),
                   compress_count=d.get("compress_count", 0))
        conv.messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return conv


@dataclass
class UserProfile:
    user_id: str
    username: str = ""
    first_seen: str = ""
    last_seen: str = ""
    message_count: int = 0
    interests: list[str] = field(default_factory=list)
    personality: str = ""
    chat_style: str = ""
    notable_facts: list[str] = field(default_factory=list)
    relationship: str = "陌生人"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ContextEngine:
    """上下文引擎 — 管理短期记忆和长期画像"""

    def __init__(self):
        for d in [CONV_DIR, PROFILE_DIR, ARCHIVE_DIR]:
            d.mkdir(parents=True, exist_ok=True)
        self._convs: dict[str, Conversation] = {}
        self._profiles: dict[str, UserProfile] = {}

    @staticmethod
    def _safe_name(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", s)

    def is_noise(self, content: str) -> bool:
        if not content or not content.strip():
            return True
        for p in NOISE_PATTERNS:
            if p.match(content.strip()):
                return True
        return False

    # ---- 对话 ----

    def get_conversation(self, conv_id: str) -> Conversation:
        if conv_id not in self._convs:
            fp = CONV_DIR / f"{self._safe_name(conv_id)}.json"
            if fp.exists():
                try:
                    self._convs[conv_id] = Conversation.from_dict(json.loads(fp.read_text(encoding="utf-8")))
                    return self._convs[conv_id]
                except Exception:
                    pass
            self._convs[conv_id] = Conversation(
                conv_id=conv_id, created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat())
        return self._convs[conv_id]

    def add_message(self, conv_id: str, msg: Message) -> bool:
        if self.is_noise(msg.content) and not msg.has_image:
            return False
        conv = self.get_conversation(conv_id)
        # 存储层去重兜底: 与上一条用户消息完全相同则不入库，防止 QQ 重投/外层去重
        # 失效时把重复消息写进历史，导致模型误判"用户重复问"。
        if msg.role == "user" and conv.messages:
            last = conv.messages[-1]
            if last.role == "user" and last.content == msg.content and not msg.has_image:
                return False
        conv.add(msg)
        self._save_conv(conv)
        return conv.needs_compress()

    def get_context_messages(self, conv_id: str, limit: int = None) -> list[Message]:
        limit = limit or CONTEXT["max_turns"]
        conv = self.get_conversation(conv_id)
        return conv.messages[-limit * 2:]

    def get_context_string(self, conv_id: str) -> str:
        return "\n".join(
            f"[{m.username or m.user_id or '用户'}]: {m.content}" if m.role == "user"
            else f"[Bot]: {m.content}"
            for m in self.get_context_messages(conv_id)
        )

    def build_compression_prompt(self, conv_id: str) -> str:
        return f"""你是一个对话摘要专家。请对以下QQ群聊/私聊对话进行压缩。

要求:
1. 保留所有重要信息: 用户身份、偏好、关键事实、决策、承诺
2. 保留情感表达和态度变化
3. 保留所有涉及人名、时间、地点、数字的具体信息
4. 过滤纯灌水、重复消息、无意义表情
5. 按时间顺序组织，标注关键节点
6. 输出格式: 先写"## 对话摘要"，然后按时间线写关键节点，最后写"## 保留的关键信息"列表

原始对话:
{self.get_context_string(conv_id)}"""

    def apply_compression(self, conv_id: str, summary: str, original_chars: int):
        conv = self.get_conversation(conv_id)
        conv.compress_count += 1
        archive_path = ARCHIVE_DIR / f"{self._safe_name(conv_id)}_compress_{conv.compress_count}.md"
        archive_path.write_text(
            f"# 对话压缩存档\n- 对话ID: {conv_id}\n- 压缩时间: {datetime.now().isoformat()}\n"
            f"- 原始字符数: {original_chars}\n- 压缩次数: {conv.compress_count}\n\n{summary}",
            encoding="utf-8")
        conv.messages = [
            Message(role="system",
                    content=f"[对话历史摘要 - 第{conv.compress_count}次压缩]\n{summary}",
                    timestamp=datetime.now().isoformat())
        ]
        conv.total_chars = len(conv.messages[0].content)
        conv.updated_at = datetime.now().isoformat()
        self._save_conv(conv)

    def _save_conv(self, conv: Conversation):
        fp = CONV_DIR / f"{self._safe_name(conv.conv_id)}.json"
        fp.write_text(json.dumps(conv.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 用户画像 ----

    def get_profile(self, user_id: str) -> UserProfile:
        if user_id not in self._profiles:
            fp = PROFILE_DIR / f"{self._safe_name(user_id)}.json"
            if fp.exists():
                try:
                    self._profiles[user_id] = UserProfile.from_dict(json.loads(fp.read_text(encoding="utf-8")))
                    return self._profiles[user_id]
                except Exception:
                    pass
            self._profiles[user_id] = UserProfile(user_id=user_id, first_seen=datetime.now().isoformat())
        return self._profiles[user_id]

    def update_profile(self, user_id: str, username: str, message: str):
        p = self.get_profile(user_id)
        p.username = username
        p.last_seen = datetime.now().isoformat()
        p.message_count += 1

        if p.message_count > 100: p.relationship = "老熟人"
        elif p.message_count > 30: p.relationship = "朋友"
        elif p.message_count > 5: p.relationship = "群友"

        interest_kw = {
            "篮球": ["篮球", "NBA", "打球", "库里", "詹姆斯", "科比", "坤坤"],
            "音乐": ["音乐", "唱歌", "歌曲", "听歌", "rap", "Rap", "KTV"],
            "游戏": ["游戏", "LOL", "王者", "原神", "吃鸡"],
            "编程": ["代码", "编程", "Python", "bug", "程序"],
            "动漫": ["动漫", "番剧", "二次元", "cos"],
            "舞蹈": ["舞蹈", "跳舞", "街舞", "hiphop"],
            "科技": ["AI", "人工智能", "手机", "芯片"],
        }
        for interest, keywords in interest_kw.items():
            if any(kw in message for kw in keywords) and interest not in p.interests:
                p.interests.append(interest)

        if len(message) < 5: p.chat_style = "简洁型"
        elif len(message) > 100: p.chat_style = "话痨型"
        elif "哈哈哈" in message or "笑死" in message: p.chat_style = "幽默型"

        self._save_profile(p)

    def get_profile_summary(self, user_id: str) -> str:
        p = self.get_profile(user_id)
        if p.message_count == 0:
            return ""
        parts = [f"用户 {p.username or user_id}"]
        if p.relationship != "陌生人": parts.append(f"关系: {p.relationship}")
        if p.interests: parts.append(f"兴趣: {', '.join(p.interests[:5])}")
        if p.chat_style: parts.append(f"风格: {p.chat_style}")
        if p.notable_facts: parts.append(f"备注: {'; '.join(p.notable_facts[:3])}")
        return " | ".join(parts)

    def _save_profile(self, p: UserProfile):
        fp = PROFILE_DIR / f"{self._safe_name(p.user_id)}.json"
        fp.write_text(json.dumps(p.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def stats(self) -> dict:
        return {
            "active_conversations": len(self._convs),
            "total_profiles": len(self._profiles),
            "total_archives": len(list(ARCHIVE_DIR.glob("*.md"))),
        }


_engine: Optional[ContextEngine] = None

def get_engine() -> ContextEngine:
    global _engine
    if _engine is None:
        _engine = ContextEngine()
    return _engine