#!/usr/bin/env python3
"""
QQ Bot ↔ HORIZON LLM 桥接服务 v2.0
==================================
完整功能:
  - QQ Bot WebSocket 长连接 (自动重连)
  - 多模型智能路由 (DeepSeek-Pro | MiniMax | GLM)
  - 上下文工程 (1M字符窗口, 自动压缩, 无效过滤)
  - 用户画像系统 (长期记忆, 兴趣追踪, 关系升级)
  - ikun人设 (AGENT.md 驱动)
  - 开机自启动 (Windows Service)

模型路由:
  纯文本 → HORIZON-DeepSeek-Pro
  带图片 → HORIZON-MiniMax (视觉)
  失败回退 → HORIZON-GLM
"""

import asyncio, json, os, sys, time, re, signal, traceback
from datetime import datetime
from pathlib import Path

# Windows UTF-8 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import aiohttp

from context_engine import (
    ContextEngine, Message, get_engine,
    is_noise, MAX_CONTEXT_CHARS, COMPRESS_THRESHOLD,
)

# ============================================================
# 配置
# ============================================================

BASE_DIR = Path(__file__).parent

# QQ Bot 配置
QQ_BOT_CONFIG = {
    "app_id": "1903593494",
    "app_secret": "ppqrtvy15AFLRYfnv4EOZkw8LYm0FUk1",
    "api_host": "https://api.sgroup.qq.com",
    "gateway_host": "api.sgroup.qq.com",
}

# HORIZON API 配置
HORIZON_CONFIG = {
    "base_url": "https://llmapi.horizon.auto/v1",
    "auth_token": "eVSJLuMvTKkv5col",
    "timeout": 120,
}

# 模型配置
MODEL_CONFIG = {
    "default": "HORIZON-DeepSeek-Pro",
    "vision": "HORIZON-MiniMax",
    "fallback": "HORIZON-GLM",
    "compressor": "HORIZON-DeepSeek-Pro",  # 压缩任务用最强文本模型
    "max_tokens": 2048,
    "temperature": 0.7,
}

# 加载 AGENT.md 作为 system prompt
def load_system_prompt() -> str:
    agent_md = BASE_DIR / "AGENT.md"
    if agent_md.exists():
        content = agent_md.read_text(encoding="utf-8")
        # 去掉 YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            content = parts[2] if len(parts) > 2 else content
        return f"""你是一个通过QQ接入的AI助手。请严格按照以下人设和行为准则行动：

{content.strip()}

重要提醒:
- 回复使用纯文本格式，不要用Markdown
- 群聊中回复控制在200字以内
- 私聊可以适当长一些，但不超过500字
- 保持自然，像真人聊天"""
    return "你是一个友好的QQ Bot AI助手，回复简洁、使用中文。"

SYSTEM_PROMPT = load_system_prompt()

# 群白名单 (空=全部允许)
ALLOWED_GROUP_IDS: list[str] = []

# ============================================================
# 全局状态
# ============================================================

access_token = None
token_expire_at = 0
session_seq = 0
session_id = ""
heartbeat_interval = 41250
ctx: ContextEngine = None  # 延迟初始化
running = True


# ============================================================
# 鉴权
# ============================================================

async def get_access_token() -> str:
    global access_token, token_expire_at
    if access_token and time.time() < token_expire_at - 60:
        return access_token

    url = "https://bots.qq.com/app/getAppAccessToken"
    payload = {
        "appId": QQ_BOT_CONFIG["app_id"],
        "clientSecret": QQ_BOT_CONFIG["app_secret"],
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as resp:
            data = await resp.json()
            print(f"[Auth] getAccessToken → {json.dumps(data, ensure_ascii=False)}")

    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"获取 access_token 失败: {data}")

    token_expire_at = time.time() + int(data.get("expires_in", 7200))
    print(f"[Auth] Token获取成功, 过期: {datetime.fromtimestamp(token_expire_at)}")
    return access_token


# ============================================================
# WebSocket 协议
# ============================================================

def build_identify(token: str) -> dict:
    return {
        "op": 2,
        "d": {
            "token": f"QQBot {token}",
            "intents": 1 << 25 | 1 << 0,
            "shard": [0, 1],
            "properties": {
                "$os": "linux",
                "$browser": "qbot-ikun",
                "$device": "qbot-ikun",
            },
        },
    }

def build_heartbeat() -> dict:
    return {"op": 1, "d": session_seq}


# ============================================================
# 消息提取
# ============================================================

def get_conversation_id(payload: dict) -> str:
    if "group_id" in payload:
        return f"group_{payload['group_id']}"
    if "guild_id" in payload:
        return f"guild_{payload['guild_id']}_channel_{payload.get('channel_id', '')}"
    return f"user_{payload.get('author', {}).get('id', 'unknown')}"


def extract_message(payload: dict) -> tuple[str, str, dict, list[str]]:
    conv_id = get_conversation_id(payload)
    content = payload.get("content", "").strip()
    content = re.sub(r"<@!\d+>", "", content).strip()

    attachments = payload.get("attachments", [])
    image_urls = []
    for att in attachments:
        ct = att.get("content_type", "")
        url = att.get("url", "")
        fn = att.get("filename", "").lower()
        if ct.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            image_urls.append(url)
        else:
            content += f"\n[附件: {att.get('filename', 'unknown')}]"

    extra = {
        "author_id": payload.get("author", {}).get("id", ""),
        "author_username": payload.get("author", {}).get("username", ""),
        "message_id": payload.get("id", ""),
        "timestamp": payload.get("timestamp", ""),
    }
    return content, conv_id, extra, image_urls


# ============================================================
# 模型响应清理
# ============================================================

def clean_response(content: str, model: str) -> str:
    """清理模型输出"""
    if model == MODEL_CONFIG["vision"] or "minimax" in model.lower():
        if " response" in content:
            parts = content.rsplit(" response", 1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()
    return content.strip()


# ============================================================
# HORIZON API 调用
# ============================================================

def select_model(has_image: bool, is_compression: bool = False) -> str:
    if is_compression:
        return MODEL_CONFIG["compressor"]
    if has_image:
        return MODEL_CONFIG["vision"]
    return MODEL_CONFIG["default"]


async def call_horizon(
    user_message: str,
    conv_id: str,
    username: str,
    user_id: str,
    image_urls: list[str],
    http_session: aiohttp.ClientSession,
    is_compression: bool = False,
) -> str:
    model = select_model(has_image=bool(image_urls), is_compression=is_compression)

    # 构建用户画像摘要
    profile_summary = ctx.get_profile_summary(user_id) if user_id else ""

    # 构建消息列表
    api_messages = []

    if not is_compression:
        # 添加上下文摘要 (如果有压缩历史)
        conv = ctx.get_conversation(conv_id)
        for msg in conv.messages:
            if msg.role == "system":
                api_messages.append({"role": "system", "content": msg.content})

        # 添加上下文中的最近消息
        context_msgs = ctx.get_context_messages(conv_id)
        for msg in context_msgs:
            if msg.role == "system":
                continue
            name = msg.username or msg.user_id
            label = f"[{name}]: {msg.content}"
            api_messages.append({"role": msg.role, "content": label})

    # 添加当前消息
    if image_urls:
        user_content = []
        if user_message:
            user_content.append({"type": "text", "text": f"[{username}]: {user_message}"})
        else:
            user_content.append({"type": "text", "text": f"[{username}] 发了一张图片"})
        for img_url in image_urls:
            user_content.append({"type": "image_url", "image_url": {"url": img_url}})
        api_messages.append({"role": "user", "content": user_content})
    else:
        api_messages.append({"role": "user", "content": f"[{username}]: {user_message}"})

    # 系统提示 (包含人设和用户画像)
    system = SYSTEM_PROMPT
    if profile_summary:
        system += f"\n\n当前用户信息: {profile_summary}"

    headers = {
        "Authorization": f"Bearer {HORIZON_CONFIG['auth_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *api_messages],
        "max_tokens": MODEL_CONFIG["max_tokens"],
        "temperature": MODEL_CONFIG["temperature"],
    }

    url = f"{HORIZON_CONFIG['base_url']}/chat/completions"
    print(f"[LLM] → {model} (compression={is_compression}, has_image={bool(image_urls)})")

    try:
        async with http_session.post(
            url, headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=HORIZON_CONFIG["timeout"]),
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                print(f"[LLM] API错误 {resp.status}: {json.dumps(data, ensure_ascii=False)[:300]}")
                if not is_compression:
                    return await call_horizon_fallback(user_message, conv_id, username, http_session)
                return ""

            reply = clean_response(data["choices"][0]["message"]["content"].strip(), model)
            print(f"[LLM] ← {reply[:100]}...")
            return reply

    except asyncio.TimeoutError:
        print(f"[LLM] 超时")
        if not is_compression:
            return await call_horizon_fallback(user_message, conv_id, username, http_session)
        return ""
    except Exception as e:
        print(f"[LLM] 调用失败: {e}")
        if not is_compression:
            return await call_horizon_fallback(user_message, conv_id, username, http_session)
        return ""


async def call_horizon_fallback(
    user_message: str, conv_id: str, username: str, http_session: aiohttp.ClientSession,
) -> str:
    """回退到 GLM"""
    model = MODEL_CONFIG["fallback"]
    headers = {
        "Authorization": f"Bearer {HORIZON_CONFIG['auth_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[{username}]: {user_message}"},
        ],
        "max_tokens": MODEL_CONFIG["max_tokens"],
        "temperature": MODEL_CONFIG["temperature"],
    }
    url = f"{HORIZON_CONFIG['base_url']}/chat/completions"
    print(f"[LLM] 回退 → {model}")

    try:
        async with http_session.post(
            url, headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=HORIZON_CONFIG["timeout"]),
        ) as resp:
            data = await resp.json()
            return clean_response(data["choices"][0]["message"]["content"].strip(), model)
    except Exception as e:
        print(f"[LLM] 回退也失败: {e}")
        return "抱歉，我暂时无法处理你的消息，请稍后再试~ 🏀"


# ============================================================
# 上下文压缩
# ============================================================

async def compress_context(conv_id: str, http_session: aiohttp.ClientSession):
    """压缩对话上下文"""
    conv = ctx.get_conversation(conv_id)
    original_chars = conv.total_chars

    prompt = ctx.build_compression_prompt(conv_id)
    summary = await call_horizon(
        user_message=prompt,
        conv_id=conv_id,
        username="系统",
        user_id="",
        image_urls=[],
        http_session=http_session,
        is_compression=True,
    )

    if summary:
        ctx.apply_compression(conv_id, summary, original_chars)
        print(f"[Compress] {conv_id}: {original_chars} → {conv.total_chars} 字符 (压缩 #{conv.compress_count})")
    else:
        print(f"[Compress] {conv_id}: 压缩失败，保留原上下文")


# ============================================================
# 回复发送
# ============================================================

async def send_reply(session: aiohttp.ClientSession, payload: dict, event_type: str, text: str) -> bool:
    token = await get_access_token()
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }

    if event_type == "GROUP_AT_MESSAGE_CREATE":
        group_id = payload.get("group_id")
        msg_id = payload.get("id")
        url = f"{QQ_BOT_CONFIG['api_host']}/v2/groups/{group_id}/messages"
        body = {"content": text, "msg_type": 0, "msg_id": msg_id, "msg_seq": 1}
    elif event_type == "C2C_MESSAGE_CREATE":
        openid = payload.get("author", {}).get("id", "")
        msg_id = payload.get("id")
        url = f"{QQ_BOT_CONFIG['api_host']}/v2/users/{openid}/messages"
        body = {"content": text, "msg_type": 0, "msg_id": msg_id, "msg_seq": 1}
    elif event_type == "AT_MESSAGE_CREATE":
        channel_id = payload.get("channel_id", "")
        msg_id = payload.get("id")
        url = f"{QQ_BOT_CONFIG['api_host']}/channels/{channel_id}/messages"
        body = {"content": text, "msg_id": msg_id}
    else:
        print(f"[Send] 未知消息类型: {event_type}")
        return False

    print(f"[Send] → {url}")
    async with session.post(url, headers=headers, json=body) as resp:
        data = await resp.json()
        print(f"[Send] {resp.status} {json.dumps(data, ensure_ascii=False)[:200]}")
        return resp.status == 200


# ============================================================
# 事件分发
# ============================================================

async def handle_event(event: dict, session: aiohttp.ClientSession):
    global session_seq
    session_seq = event.get("s", session_seq)

    op = event.get("op")
    t = event.get("t")
    d = event.get("d", {})

    if op == 10:
        global heartbeat_interval
        heartbeat_interval = d.get("heartbeat_interval", 41250)
        print(f"[Gateway] HELLO, heartbeat={heartbeat_interval}ms")

    elif op == 11:
        pass

    elif op == 0:
        if t in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE", "AT_MESSAGE_CREATE"):
            if t == "GROUP_AT_MESSAGE_CREATE":
                group_id = d.get("group_id", "")
                if ALLOWED_GROUP_IDS and group_id not in ALLOWED_GROUP_IDS:
                    return

            content, conv_id, extra, image_urls = extract_message(d)
            username = extra["author_username"] or extra["author_id"]
            user_id = extra["author_id"]

            img_info = f", {len(image_urls)}张图片" if image_urls else ""
            print(f"[Event] {t} from {username} ({conv_id}): {content[:80]}{img_info}")

            if not content and not image_urls:
                return

            # 更新用户画像
            if user_id:
                ctx.update_profile(user_id, username, content)

            # 记录用户消息到上下文
            needs_compress = ctx.add_message(conv_id, Message(
                role="user", content=content,
                username=username, user_id=user_id,
                timestamp=datetime.now().isoformat(),
                has_image=bool(image_urls),
            ))

            # 生成回复
            reply = await call_horizon(content, conv_id, username, user_id, image_urls, session)

            # 记录Bot回复
            ctx.add_message(conv_id, Message(
                role="assistant", content=reply,
                username="Bot", user_id="",
                timestamp=datetime.now().isoformat(),
            ))

            await send_reply(session, d, t, reply)

            # 检查是否需要压缩
            if needs_compress or ctx.get_conversation(conv_id).needs_compress():
                asyncio.create_task(compress_context(conv_id, session))

        elif t == "READY":
            global session_id
            session_id = d.get("session_id", "")
            print(f"[Gateway] READY! session_id={session_id}")

        elif t == "RESUMED":
            print("[Gateway] RESUME成功 ✓")

    elif op == 7:
        print("[Gateway] 服务端要求重连")

    elif op == 9:
        print("[Gateway] INVALID_SESSION，需要重新鉴权")


# ============================================================
# 心跳 & 主循环
# ============================================================

async def heartbeat_loop(ws: aiohttp.ClientWebSocketResponse):
    interval = heartbeat_interval / 1000
    while running:
        await asyncio.sleep(interval)
        try:
            await ws.send_json(build_heartbeat())
            print(f"[Heartbeat] seq={session_seq}")
        except Exception as e:
            print(f"[Heartbeat] 失败: {e}")
            break


async def run():
    global ctx, running
    ctx = get_engine()

    print("=" * 60)
    print("  QQ Bot ↔ HORIZON LLM 桥接服务 v2.0")
    print(f"  AppID: {QQ_BOT_CONFIG['app_id']}")
    print(f"  默认模型: {MODEL_CONFIG['default']}")
    print(f"  视觉模型: {MODEL_CONFIG['vision']}")
    print(f"  备用模型: {MODEL_CONFIG['fallback']}")
    print(f"  API网关: {HORIZON_CONFIG['base_url']}")
    print(f"  上下文窗口: {MAX_CONTEXT_CHARS:,} 字符")
    print(f"  压缩阈值: {COMPRESS_THRESHOLD:,} 字符")
    print(f"  Agent: ikun-小黑子")
    print("=" * 60)

    while running:
        try:
            token = await get_access_token()
            gateway_url = f"wss://{QQ_BOT_CONFIG['gateway_host']}/websocket"
            print(f"[Gateway] 连接 {gateway_url} ...")

            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(gateway_url) as ws:
                    print("[Gateway] WebSocket已连接")
                    await ws.send_json(build_identify(token))
                    print("[Gateway] 已发送IDENTIFY")

                    hb_task = asyncio.create_task(heartbeat_loop(ws))

                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    event = json.loads(msg.data)
                                    await handle_event(event, session)
                                except json.JSONDecodeError as e:
                                    print(f"[Gateway] JSON解析失败: {e}")
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                print("[Gateway] 连接关闭")
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print(f"[Gateway] 错误: {ws.exception()}")
                                break
                    except asyncio.CancelledError:
                        pass
                    finally:
                        hb_task.cancel()
                        try:
                            await hb_task
                        except asyncio.CancelledError:
                            pass

        except Exception as e:
            print(f"[Gateway] 连接异常: {e}")
            traceback.print_exc()

        if running:
            wait = 5
            print(f"[Gateway] {wait}秒后重连...")
            await asyncio.sleep(wait)


def shutdown(signum=None, frame=None):
    global running
    print("\n[Shutdown] 收到退出信号，正在关闭...")
    running = False


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[Shutdown] 用户中断")
    except Exception as e:
        print(f"[Fatal] {e}")
        traceback.print_exc()