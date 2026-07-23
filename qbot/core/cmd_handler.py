"""
指令系统 — QBot 斜杠命令处理

支持的命令:
  /模型      → 查看/切换模型
  /人设      → 查看/设置自定义人设
  /任务      → 切换任务模式 (编程/写作/翻译/总结/聊天)
  /状态      → 查看当前配置
  /重置      → 恢复默认设置
  /帮助      → 显示帮助

每个用户独立维护自己的设置状态。
"""
import json, re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

from ..config import DATA_DIR, MODELS

USERSTATE_DIR = DATA_DIR / "user_states"
USERSTATE_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 任务模式预设
# ============================================================

TASK_MODES = {
    "聊天": {
        "name": "聊天",
        "emoji": "💬",
        "prompt": "你是小黑子，一个QQ群里的AI助手。用轻松自然的口吻和用户聊天，像朋友一样。不要长篇大论，不要结构化回答。",
        "max_tokens": 1000,
    },
    "编程": {
        "name": "编程",
        "emoji": "💻",
        "prompt": "你是一个编程助手。请帮助用户解决编程问题：分析代码、解释概念、提供代码示例。用简洁清晰的中文回答，代码示例用纯文本展示（不要用markdown代码块）。",
        "max_tokens": 3000,
    },
    "写作": {
        "name": "写作",
        "emoji": "✍️",
        "prompt": "你是一个写作助手。帮助用户润色文字、撰写文章、修改文案。给出具体建议，解释为什么这样改更好。回复友好专业。",
        "max_tokens": 3000,
    },
    "翻译": {
        "name": "翻译",
        "emoji": "🌐",
        "prompt": "你是一个翻译助手。将用户输入精确翻译，保持原文语气和风格。如果用户未指定目标语言，默认中译英或英译中。直接给出翻译结果，不需要额外解释。",
        "max_tokens": 2000,
    },
    "总结": {
        "name": "总结",
        "emoji": "📝",
        "prompt": "你是一个总结助手。将用户提供的内容精炼为简洁的要点总结。抓住核心信息，去除冗余，用清晰的短句表达。",
        "max_tokens": 2000,
    },
    "知识": {
        "name": "知识",
        "emoji": "📚",
        "prompt": "你是一个知识问答助手。请准确、详实地回答用户的问题。引用可靠来源，区分事实和观点。如果不确定，诚实告知。",
        "max_tokens": 3000,
    },
    "创意": {
        "name": "创意",
        "emoji": "🎨",
        "prompt": "你是一个创意伙伴。帮助用户头脑风暴、产生灵感、构思方案。大胆想象，给出有趣的想法，同时保持建设性。",
        "max_tokens": 2500,
    },
}

# 可选模型列表
AVAILABLE_MODELS = [
    {"id": "HORIZON-DeepSeek-Pro", "name": "DeepSeek-Pro", "desc": "文本理解最强，默认模型"},
    {"id": "HORIZON-MiniMax", "name": "MiniMax", "desc": "视觉模型，能看懂图片"},
    {"id": "HORIZON-GLM", "name": "GLM", "desc": "备用模型，稳定可靠"},
]

# ============================================================
# 用户状态
# ============================================================

@dataclass
class UserState:
    user_id: str
    custom_model: str = ""          # 自定义模型 (空=使用默认)
    custom_persona: str = ""        # 自定义人设提示词
    task_mode: str = "聊天"          # 当前任务模式
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "UserState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class StateManager:
    """管理每个用户的状态"""

    def __init__(self):
        USERSTATE_DIR.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", user_id)
        return USERSTATE_DIR / f"{safe}.json"

    def get(self, user_id: str) -> UserState:
        p = self._path(user_id)
        if p.exists():
            try:
                return UserState.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        s = UserState(user_id=user_id, created_at=datetime.now().isoformat())
        self.save(s)
        return s

    def save(self, state: UserState):
        state.updated_at = datetime.now().isoformat()
        self._path(state.user_id).write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def get_model(self, user_id: str) -> str:
        m = self.get(user_id).custom_model
        return m if m else MODELS["default"]

    def get_system_prompt(self, user_id: str, base_prompt: str) -> str:
        """组装最终 system prompt: 基础人设 + 任务模式 + 自定义人设"""
        state = self.get(user_id)
        parts = []

        # 自定义人设优先级最高
        if state.custom_persona:
            parts.append(state.custom_persona)
        else:
            parts.append(base_prompt)

        # 任务模式
        if state.task_mode != "聊天":
            mode = TASK_MODES.get(state.task_mode)
            if mode:
                parts.append(f"\n当前任务模式: {mode['name']}\n{mode['prompt']}")

        parts.append("\n回复格式: 纯文本，不要Markdown，像真人聊天一样自然。")
        return "\n".join(parts)

    def get_max_tokens(self, user_id: str) -> int:
        mode = TASK_MODES.get(self.get(user_id).task_mode, {})
        return mode.get("max_tokens", 1000)


# 全局单例
_states = StateManager()

def get_states() -> StateManager:
    return _states


# ============================================================
# 内容安全过滤 — 违规词/违规内容检测
# ============================================================

# 违规词库基线 (按类别)。可在 data/banned_words.json 追加，运行时合并。
_BANNED_BASELINE = {
    "色情低俗": [
        "色情", "裸聊", "裸照", "一夜情", "援交", "找小姐", "包夜",
        "成人视频", "淫秽", "卖淫", "嫖娼", " AV ", "资源站",
    ],
    "暴力恐怖": [
        "炸弹制作", "杀人方法", "投毒", "自制枪支", "爆炸物配方",
        "恐怖袭击", "极端组织", "自残", "教唆自杀",
    ],
    "违法犯罪": [
        "买卖身份证", "洗钱教程", "黑产", "诈骗话术", "传销组织",
        "贩卖毒品", "代写论文保证通过", "代考", "伪造证件", "黑客攻击教程",
    ],
    "政治敏感": [
        "反动", "颠覆国家", "分裂国家", "煽动民族仇恨",
    ],
    "辱骂攻击": [
        "滚出中国", "去死", "弱智", "脑残", "傻逼", "废物",
    ],
    "隐私泄露": [
        "人肉搜索", "开盒", "查开房", "查同住", "身份证查询",
    ],
}

# 违规内容的外部补充文件 (JSON: {"色情低俗": [...], ...})，可选。
_BANNED_FILE = DATA_DIR / "banned_words.json"


class ContentFilter:
    """内容安全过滤器：检测违规词并返回类别。"""

    def __init__(self):
        self._load_keywords()

    def _load_keywords(self):
        # 合并基线与外部文件
        merged = {k: list(v) for k, v in _BANNED_BASELINE.items()}
        if _BANNED_FILE.exists():
            try:
                extra = json.loads(_BANNED_FILE.read_text(encoding="utf-8"))
                for cat, words in extra.items():
                    merged.setdefault(cat, [])
                    merged[cat].extend(words)
            except Exception:
                pass
        # 归一化：去空白、转小写，便于匹配绕过
        self._cats = {}
        for cat, words in merged.items():
            norm = []
            for w in words:
                nw = self._norm(w)
                if nw:
                    norm.append(nw)
            self._cats[cat] = sorted(set(norm), key=len, reverse=True)

    @staticmethod
    def _norm(text: str) -> str:
        """归一化：去全部空白、转小写，对抗插空格/符号绕过。"""
        return re.sub(r"\s+", "", text).lower()

    def check(self, text: str) -> dict:
        """
        检查文本是否违规。
        返回: {"violation": bool, "category": str, "matched": str}
        """
        if not text:
            return {"violation": False, "category": "", "matched": ""}
        norm = self._norm(text)
        for cat, words in self._cats.items():
            for w in words:
                if w and w in norm:
                    return {"violation": True, "category": cat, "matched": w}
        return {"violation": False, "category": "", "matched": ""}

    def is_safe(self, text: str) -> bool:
        return not self.check(text)["violation"]


# 全局单例
_filter = ContentFilter()

def get_filter() -> "ContentFilter":
    return _filter


# ============================================================
# 指令处理
# ============================================================

class CommandHandler:
    """斜杠指令处理器"""

    @staticmethod
    def is_command(content: str) -> bool:
        return content.strip().startswith("/")

    @staticmethod
    def parse(content: str) -> tuple[str, str]:
        """解析指令: /模型 DeepSeek → ("模型", "DeepSeek")"""
        parts = content.strip().split(maxsplit=1)
        cmd = parts[0].lstrip("/")
        arg = parts[1] if len(parts) > 1 else ""
        return cmd, arg

    @staticmethod
    def handle(content: str, user_id: str, username: str) -> str:
        cmd, arg = CommandHandler.parse(content)
        states = get_states()
        state = states.get(user_id)

        if cmd in ("帮助", "help"):
            return CommandHandler._help()

        elif cmd == "模型":
            return CommandHandler._model(state, arg, user_id, states)

        elif cmd == "人设":
            return CommandHandler._persona(state, arg, user_id, states)

        elif cmd == "任务":
            return CommandHandler._task(state, arg, user_id, states)

        elif cmd == "状态":
            return CommandHandler._status(state)

        elif cmd == "重置":
            return CommandHandler._reset(state, user_id, states)

        else:
            return f"未知指令 /{cmd}，输入 /帮助 查看可用指令"

    # ---- 帮助 ----

    @staticmethod
    def _help() -> str:
        return """可用指令：
/模型 - 查看/切换AI模型
/人设 - 查看/设置自定义人设
/任务 - 切换任务模式（编程/写作/翻译/总结/知识/创意/聊天）
/状态 - 查看当前配置
/重置 - 恢复默认设置
/帮助 - 显示此帮助

使用方式：发送 /指令 即可，例如 /模型"""

    # ---- 模型切换 ----

    @staticmethod
    def _model(state: UserState, arg: str, user_id: str, states: StateManager) -> str:
        if not arg:
            lines = ["当前可用模型："]
            current = states.get_model(user_id)
            for i, m in enumerate(AVAILABLE_MODELS, 1):
                marker = " ← 当前" if m["id"] == current else ""
                lines.append(f"{i}. {m['name']} - {m['desc']}{marker}")
            lines.append("\n回复数字切换模型，例如发送 /模型 1")
            return "\n".join(lines)

        # 数字选择
        try:
            idx = int(arg) - 1
            if 0 <= idx < len(AVAILABLE_MODELS):
                model = AVAILABLE_MODELS[idx]
                state.custom_model = model["id"]
                states.save(state)
                return f"已切换到 {model['name']}，下次对话生效 🎯"
            else:
                return f"请输入 1-{len(AVAILABLE_MODELS)} 之间的数字"
        except ValueError:
            # 尝试按名称匹配
            for m in AVAILABLE_MODELS:
                if arg.lower() in m["name"].lower() or arg.lower() in m["id"].lower():
                    state.custom_model = m["id"]
                    states.save(state)
                    return f"已切换到 {m['name']} 🎯"
            return f"未找到模型 '{arg}'，输入 /模型 查看列表"

    # ---- 人设设置 ----

    @staticmethod
    def _persona(state: UserState, arg: str, user_id: str, states: StateManager) -> str:
        if not arg:
            current = state.custom_persona or "（使用默认人设）"
            return f"""当前人设：{current}

设置新人设：发送 /人设 [你的描述]
例如：/人设 你是一个高冷的技术专家，只回答技术问题，不闲聊

清除自定义人设：发送 /人设 清除"""

        if arg.strip() == "清除":
            state.custom_persona = ""
            states.save(state)
            return "已清除自定义人设，恢复默认 ✅"

        # 内容安全过滤：自定义人设禁止违规词
        result = get_filter().check(arg)
        if result["violation"]:
            return f"⚠️ 人设内容含违规内容（类别：{result['category']}），已拒绝设置。请修改后重试。"

        state.custom_persona = arg.strip()
        states.save(state)
        return f"人设已更新 ✅\n新设定：{arg.strip()[:150]}"

    # ---- 任务模式 ----

    @staticmethod
    def _task(state: UserState, arg: str, user_id: str, states: StateManager) -> str:
        if not arg:
            lines = ["可选任务模式："]
            current = state.task_mode
            for i, (name, mode) in enumerate(TASK_MODES.items(), 1):
                marker = " ← 当前" if name == current else ""
                lines.append(f"{i}. {mode['emoji']} {name} - {mode['prompt'][:40]}...{marker}")
            lines.append("\n回复数字切换，例如发送 /任务 2")
            return "\n".join(lines)

        # 数字选择
        try:
            idx = int(arg) - 1
            keys = list(TASK_MODES.keys())
            if 0 <= idx < len(keys):
                name = keys[idx]
                state.task_mode = name
                states.save(state)
                return f"已切换到 {TASK_MODES[name]['emoji']} {name} 模式，下次对话生效"
            else:
                return f"请输入 1-{len(keys)} 之间的数字"
        except ValueError:
            for name in TASK_MODES:
                if arg in name:
                    state.task_mode = name
                    states.save(state)
                    return f"已切换到 {TASK_MODES[name]['emoji']} {name} 模式"
            return f"未找到任务模式 '{arg}'，输入 /任务 查看列表"

    # ---- 状态 ----

    @staticmethod
    def _status(state: UserState) -> str:
        model_name = state.custom_model or "默认"
        persona = state.custom_persona[:80] + "..." if len(state.custom_persona) > 80 else (state.custom_persona or "默认")
        mode = TASK_MODES.get(state.task_mode, {})
        return f"""当前配置：
模型：{model_name}
人设：{persona}
任务：{mode.get('emoji', '')} {state.task_mode}

输入 /帮助 查看所有指令"""

    # ---- 重置 ----

    @staticmethod
    def _reset(state: UserState, user_id: str, states: StateManager) -> str:
        state.custom_model = ""
        state.custom_persona = ""
        state.task_mode = "聊天"
        states.save(state)
        return "已重置所有设置为默认值 ✅"