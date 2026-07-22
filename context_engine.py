"""
上下文引擎 — QQ Bot 知识记忆系统
==================================
功能:
  1. 短期记忆: 维护每个群聊/私聊的滑动窗口上下文 (1M字符上限)
  2. 长期记忆: 用户画像系统 (按QQ号存储偏好、兴趣、聊天风格)
  3. 自动压缩: 上下文超过1M时触发LLM压缩，提取有效信息存MD
  4. 无效过滤: 过滤纯表情、灌水、重复消息

存储结构:
  data/conversations/  → 活跃对话上下文 (JSON)
  data/profiles/       → 用户画像 (JSON, 按QQ号)
  data/archives/       → 压缩后的历史摘要 (MD)
"""

import json, os, re, time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

# ============================================================
# 配置
# ============================================================

DATA_DIR = Path(__file__).parent / "data"
CONV_DIR = DATA_DIR / "conversations"
PROFILE_DIR = DATA_DIR / "profiles"
ARCHIVE_DIR = DATA_DIR / "archives"

MAX_CONTEXT_CHARS = 1_000_000  # 1M 字符上限
MAX_TURNS = 50                 # 最多保留 50 轮对话
COMPRESS_THRESHOLD = 800_000   # 达到 800K 字符时触发压缩
COMPRESS_TARGET = 200_000      # 压缩后保留的字符数

# 无效消息模式 (不计入上下文)
NOISE_PATTERNS = [
    re.compile(r"^[，。！？,.!?\s]*$"),           # 纯标点/空白
    re.compile(r"^[\U0001F000-\U0001FFFF\U00002600-\U000027BF]+$"),  # 纯emoji
    re.compile(r"^(?:哈哈|呵呵|嗯嗯|哦哦|666|ddd|草){1,10}$"),        # 纯灌水
    re.compile(r"^[\[\]【】\-\+=~`@#$%^&*()_]{1,20}$"),              # 纯符号
]

# ============================================================
# 数据结构
# ============================================================

@dataclass
class Message:
    """单条消息"""
    role: str           # "user" | "assistant"
    content: str
    username: str = ""  # 发送者昵称
    user_id: str = ""   # QQ号
    timestamp: str = ""  # ISO 时间
    has_image: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(**d)

    def char_count(self) -> int:
        return len(self.content)


@dataclass
class Conversation:
    """对话上下文"""
    conv_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    total_chars: int = 0
    compress_count: int = 0

    def add_message(self, msg: Message):
        self.messages.append(msg)
        self.total_chars += msg.char_count()
        self.updated_at = datetime.now().isoformat()

    def needs_compress(self) -> bool:
        return self.total_chars > COMPRESS_THRESHOLD or len(self.messages) > MAX_TURNS

    def to_dict(self) -> dict:
        return {
            "conv_id": self.conv_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_chars": self.total_chars,
            "compress_count": self.compress_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        conv = cls(
            conv_id=d["conv_id"],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            total_chars=d.get("total_chars", 0),
            compress_count=d.get("compress_count", 0),
        )
        conv.messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return conv


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    username: str = ""
    first_seen: str = ""
    last_seen: str = ""
    message_count: int = 0
    interests: list[str] = field(default_factory=list)       # 兴趣爱好
    personality: str = ""  # 性格描述
    chat_style: str = ""   # 聊天风格
    notable_facts: list[str] = field(default_factory=list)    # 重要信息
    relationship: str = "陌生人"  # 与Bot的关系: 陌生人/群友/朋友/老熟人
    tags: list[str] = field(default_factory=list)            # 标签

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================================
# 无效消息过滤
# ============================================================

def is_noise(content: str) -> bool:
    """判断消息是否为无效噪声"""
    if not content or not content.strip():
        return True
    for pattern in NOISE_PATTERNS:
        if pattern.match(content.strip()):
            return True
    return False


# ============================================================
# 上下文管理器
# ============================================================

class ContextEngine:
    """上下文引擎: 管理所有对话的短期记忆和长期画像"""

    def __init__(self):
        CONV_DIR.mkdir(parents=True, exist_ok=True)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self._convs: dict[str, Conversation] = {}
        self._profiles: dict[str, UserProfile] = {}

    # ---- 对话管理 ----

    def get_conversation(self, conv_id: str) -> Conversation:
        """获取或创建对话"""
        if conv_id not in self._convs:
            # 尝试从磁盘加载
            filepath = CONV_DIR / f"{self._safe_filename(conv_id)}.json"
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        self._convs[conv_id] = Conversation.from_dict(json.load(f))
                    return self._convs[conv_id]
                except Exception:
                    pass
            conv = Conversation(
                conv_id=conv_id,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            self._convs[conv_id] = conv
        return self._convs[conv_id]

    def add_message(self, conv_id: str, msg: Message) -> bool:
        """添加消息到上下文。返回是否触发压缩"""
        if is_noise(msg.content) and not msg.has_image:
            return False  # 无效消息不记录

        conv = self.get_conversation(conv_id)
        conv.add_message(msg)

        # 持久化
        self._save_conversation(conv)

        return conv.needs_compress()

    def get_context_messages(self, conv_id: str, limit: int = MAX_TURNS) -> list[Message]:
        """获取上下文中最近N条消息"""
        conv = self.get_conversation(conv_id)
        return conv.messages[-limit * 2:]  # *2 因为每轮有 user + assistant

    def get_context_string(self, conv_id: str, limit: int = MAX_TURNS) -> str:
        """获取上下文的文本表示"""
        msgs = self.get_context_messages(conv_id, limit)
        lines = []
        for m in msgs:
            name = m.username or m.user_id or "用户"
            if m.role == "user":
                lines.append(f"[{name}]: {m.content}")
            else:
                lines.append(f"[Bot]: {m.content}")
        return "\n".join(lines)

    def clear(self, conv_id: str):
        """清空对话上下文"""
        if conv_id in self._convs:
            del self._convs[conv_id]
        filepath = CONV_DIR / f"{self._safe_filename(conv_id)}.json"
        if filepath.exists():
            filepath.unlink()

    # ---- 用户画像 ----

    def get_profile(self, user_id: str) -> UserProfile:
        """获取或创建用户画像"""
        if user_id not in self._profiles:
            filepath = PROFILE_DIR / f"{self._safe_filename(user_id)}.json"
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        self._profiles[user_id] = UserProfile.from_dict(json.load(f))
                    return self._profiles[user_id]
                except Exception:
                    pass
            self._profiles[user_id] = UserProfile(
                user_id=user_id,
                first_seen=datetime.now().isoformat(),
            )
        return self._profiles[user_id]

    def update_profile(self, user_id: str, username: str, message: str):
        """根据消息更新用户画像"""
        profile = self.get_profile(user_id)
        profile.username = username
        profile.last_seen = datetime.now().isoformat()
        profile.message_count += 1

        # 关系升级
        if profile.message_count > 100:
            profile.relationship = "老熟人"
        elif profile.message_count > 30:
            profile.relationship = "朋友"
        elif profile.message_count > 5:
            profile.relationship = "群友"

        # 兴趣检测 (简单关键词)
        interest_keywords = {
            "篮球": ["篮球", "NBA", "打球", "库里", "詹姆斯", "科比"],
            "音乐": ["音乐", "唱歌", "歌曲", "听歌", "rap", "Rap", "KTV"],
            "游戏": ["游戏", "打游戏", "LOL", "农药", "王者", "原神", "吃鸡"],
            "编程": ["代码", "编程", "Python", "bug", "程序", "开发"],
            "动漫": ["动漫", "番剧", "二次元", "cos", "Cos"],
            "舞蹈": ["舞蹈", "跳舞", "街舞", "hiphop"],
            "科技": ["AI", "人工智能", "手机", "电脑", "芯片"],
        }
        for interest, keywords in interest_keywords.items():
            if any(kw in message for kw in keywords):
                if interest not in profile.interests:
                    profile.interests.append(interest)

        # 风格检测
        if len(message) < 5:
            profile.chat_style = "简洁型"
        elif len(message) > 100:
            profile.chat_style = "话痨型"
        elif "哈哈哈" in message or "笑死" in message:
            profile.chat_style = "幽默型"

        # 保存
        self._save_profile(profile)

    def get_profile_summary(self, user_id: str) -> str:
        """获取用户画像摘要文本"""
        profile = self.get_profile(user_id)
        if profile.message_count == 0:
            return ""

        parts = [f"用户 {profile.username or user_id}"]
        if profile.relationship != "陌生人":
            parts.append(f"关系: {profile.relationship}")
        if profile.interests:
            parts.append(f"兴趣: {', '.join(profile.interests[:5])}")
        if profile.chat_style:
            parts.append(f"风格: {profile.chat_style}")
        if profile.notable_facts:
            parts.append(f"备注: {'; '.join(profile.notable_facts[:3])}")
        if profile.personality:
            parts.append(f"性格: {profile.personality}")
        return " | ".join(parts)

    # ---- 压缩 ----

    def build_compression_prompt(self, conv_id: str) -> str:
        """构建压缩提示词"""
        conv = self.get_conversation(conv_id)
        context = self.get_context_string(conv_id)
        return f"""你是一个对话摘要专家。请对以下QQ群聊/私聊对话进行压缩。

要求:
1. 保留所有重要信息: 用户身份、偏好、关键事实、决策、承诺
2. 保留情感表达和态度变化
3. 保留所有涉及人名、时间、地点、数字的具体信息
4. 过滤纯灌水、重复消息、无意义表情
5. 按时间顺序组织，标注关键节点
6. 输出格式: 先写"## 对话摘要"，然后按时间线写关键节点，最后写"## 保留的关键信息"列表

原始对话:
{context}"""

    def apply_compression(
        self,
        conv_id: str,
        summary: str,
        original_char_count: int,
    ):
        """应用压缩结果"""
        conv = self.get_conversation(conv_id)
        conv.compress_count += 1

        # 保存压缩摘要到归档
        archive_path = ARCHIVE_DIR / f"{self._safe_filename(conv_id)}_compress_{conv.compress_count}.md"
        archive_content = f"""# 对话压缩存档
- 对话ID: {conv_id}
- 压缩时间: {datetime.now().isoformat()}
- 原始字符数: {original_char_count}
- 压缩次数: {conv.compress_count}

{summary}
"""
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(archive_content)

        # 重置上下文，只保留压缩摘要作为系统消息
        conv.messages = [
            Message(
                role="system",
                content=f"[对话历史摘要 - 第{conv.compress_count}次压缩]\n{summary}",
                timestamp=datetime.now().isoformat(),
            )
        ]
        conv.total_chars = len(conv.messages[0].content)
        conv.updated_at = datetime.now().isoformat()

        self._save_conversation(conv)

    # ---- 持久化 ----

    def _save_conversation(self, conv: Conversation):
        filepath = CONV_DIR / f"{self._safe_filename(conv.conv_id)}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(conv.to_dict(), f, ensure_ascii=False, indent=2)

    def _save_profile(self, profile: UserProfile):
        filepath = PROFILE_DIR / f"{self._safe_filename(profile.user_id)}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def _safe_filename(s: str) -> str:
        """安全文件名"""
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", s)

    # ---- 统计 ----

    def stats(self) -> dict:
        return {
            "active_conversations": len(self._convs),
            "total_profiles": len(self._profiles),
            "total_archives": len(list(ARCHIVE_DIR.glob("*.md"))),
        }


# ============================================================
# 全局单例
# ============================================================

_engine: Optional[ContextEngine] = None

def get_engine() -> ContextEngine:
    global _engine
    if _engine is None:
        _engine = ContextEngine()
    return _engine