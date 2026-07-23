#!/usr/bin/env python3
"""
QBot v2.1 — QQ Bot Agent Framework
===================================
模块化架构，参考 Claude Code / Codex / Hermes Agent 设计模式。

架构:
  qbot/core/     → WebSocket 网关、LLM 客户端
  qbot/memory/   → 上下文引擎、用户画像、压缩器
  qbot/skills/   → 技能注册表 (腾讯频道等)
  qbot/tools/    → 工具集 (图片下载、消息发送等)

启动: python app.py
"""
import asyncio, json, os, sys, signal, traceback
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import aiohttp

from qbot.config import (
    QQ_BOT, HORIZON, MODELS, CONTEXT, ALLOWED_GROUPS, load_agent_prompt,
    BASE_DIR, DATA_DIR, LOG_DIR,
)
from qbot.core.gateway import QQGateway
from qbot.core.llm_client import get_llm, select_model, clean_response
from qbot.core.cmd_handler import CommandHandler, get_states, get_filter, TASK_MODES
from qbot.memory.context_engine import get_engine, Message
from qbot.tools.message_tools import MessageTool, ImageTool
from qbot.skills.channel_skill import ChannelSkill, registry as skill_registry

SYSTEM_PROMPT = load_agent_prompt()
ctx = get_engine()
llm = get_llm()
gateway = QQGateway()
running = True

# 消息幂等去重: 防止 QQ 网关重投/重连补发导致同一条消息被重复处理+回复(连发多条)。
# QQ 重投时常换用新 message_id，所以单按 message_id 去重会失效。
# 采用双重去重:
#   1) message_id 相同 → 重复 (处理重连补发)
#   2) 同会话(conv_id)+相同内容，且在 DEDUP_WINDOW 秒内 → 重复 (处理 QQ 重投新 message_id)
import time as _time
_DEDUP_WINDOW = 90  # 秒，QQ 重投通常在数十秒内
_processed_msg_ids: set[str] = set()
_recent_contents: dict[str, float] = {}  # key="conv_id|content" -> 首次处理时间戳
_PROCESSED_LIMIT = 500


def _is_duplicate(msg_id: str, conv_id: str, content: str) -> bool:
    """返回 True 表示该消息已处理过(重复)。"""
    now = _time.time()

    # 规则1: message_id 重复
    if msg_id and msg_id in _processed_msg_ids:
        return True

    # 规则2: 同会话+同内容，时间窗内重复 (QQ 重投常带新 message_id)
    if conv_id and content:
        content_key = f"{conv_id}|{content[:200]}"
        last = _recent_contents.get(content_key)
        if last is not None and (now - last) < _DEDUP_WINDOW:
            return True
        _recent_contents[content_key] = now

    # 记录 message_id
    if msg_id:
        _processed_msg_ids.add(msg_id)
        if len(_processed_msg_ids) > _PROCESSED_LIMIT:
            for old in list(_processed_msg_ids)[: _PROCESSED_LIMIT // 2]:
                _processed_msg_ids.discard(old)

    # 清理过期的内容去重记录，避免无界增长
    if len(_recent_contents) > _PROCESSED_LIMIT:
        cutoff = now - _DEDUP_WINDOW * 2
        for k in list(_recent_contents):
            if _recent_contents[k] < cutoff:
                del _recent_contents[k]

    return False


# ============================================================
# 事件处理
# ============================================================

async def handle_event(event: dict, session: aiohttp.ClientSession):
    """处理收到的 QQ Bot 事件"""
    t = event.get("t")
    d = event.get("d", {})

    if t not in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE", "AT_MESSAGE_CREATE"):
        return

    # 群白名单检查
    if t == "GROUP_AT_MESSAGE_CREATE":
        group_id = d.get("group_openid") or d.get("group_id", "")
        if ALLOWED_GROUPS and group_id not in ALLOWED_GROUPS:
            return

    content, conv_id, extra, image_urls = MessageTool.extract_message(d)
    username = extra["author_username"] or extra["author_id"]
    user_id = extra["author_id"]
    msg_id = extra["message_id"]

    # 幂等去重: message_id 相同 OR 同会话同内容90秒内 → 跳过 (防QQ重投换新message_id)
    if _is_duplicate(msg_id, conv_id, content):
        print(f"[Dedup] 跳过重复消息 (msg_id={msg_id}): {content[:40]}")
        return

    img_info = f", {len(image_urls)}张图片" if image_urls else ""
    print(f"[Event] {t} from {username} ({conv_id}): {content[:80]}{img_info}")

    if not content and not image_urls:
        return

    # 内容安全过滤: 用户输入违规直接拦截，不调用LLM
    if content:
        flt = get_filter().check(content)
        if flt["violation"]:
            print(f"[Filter] 拒绝违规输入 (类别: {flt['category']}): {content[:60]}")
            token = await gateway.get_token()
            await MessageTool.send_reply(
                session, d, t,
                f"⚠️ 你发送的内容含违规信息（类别：{flt['category']}），无法处理，请文明发言。",
                token)
            return

    # ============================================================
    # 指令拦截: /开头的消息作为指令处理，不调用LLM
    # ============================================================
    if content and CommandHandler.is_command(content):
        cmd_reply = CommandHandler.handle(content, user_id, username)
        token = await gateway.get_token()
        await MessageTool.send_reply(session, d, t, cmd_reply, token)
        return

    # 图片预处理: 下载转为base64 (QQ内部CDN MiniMax访问不了)
    image_b64s = []
    if image_urls:
        token = await gateway.get_token()
        image_b64s = await ImageTool.download_images(image_urls, session, token)
        print(f"[ImageTool] 下载了 {len(image_b64s)}/{len(image_urls)} 张图片")

    # 更新用户画像
    if user_id:
        ctx.update_profile(user_id, username, content)

    # 记录用户消息
    ctx.add_message(conv_id, Message(
        role="user", content=content,
        username=username, user_id=user_id,
        timestamp=datetime.now().isoformat(),
        has_image=bool(image_b64s),
    ))

    # 构建消息列表
    profile_summary = ctx.get_profile_summary(user_id) if user_id else ""
    conv = ctx.get_conversation(conv_id)
    api_messages = []

    # 系统消息 (压缩历史)
    for msg in conv.messages:
        if msg.role == "system":
            api_messages.append({"role": "system", "content": msg.content})

    # 上下文消息
    for msg in ctx.get_context_messages(conv_id):
        if msg.role == "system":
            continue
        name = msg.username or msg.user_id
        api_messages.append({"role": msg.role, "content": f"[{name}]: {msg.content}"})

    # 当前消息 (支持图片)
    if image_b64s:
        user_content = [{"type": "text", "text": f"[{username}]: {content}" if content else f"[{username}] 发了一张图片"}]
        for b64 in image_b64s:
            user_content.append({"type": "image_url", "image_url": {"url": b64}})
        api_messages.append({"role": "user", "content": user_content})
    else:
        api_messages.append({"role": "user", "content": f"[{username}]: {content}"})

    # 系统提示
    system = SYSTEM_PROMPT
    if profile_summary:
        system += f"\n\n当前用户信息: {profile_summary}"

    # 获取用户自定义模型和系统提示词
    states = get_states()
    system = states.get_system_prompt(user_id, system)
    model = states.get_model(user_id)
    max_tokens = states.get_max_tokens(user_id)

    # 调用 LLM
    reply = await llm.chat_with_fallback(
        messages=api_messages,
        system=system,
        has_image=bool(image_b64s),
    )

    # 内容安全过滤: 模型输出也过一遍，违规则替换为安全提示
    if reply:
        out_flt = get_filter().check(reply)
        if out_flt["violation"]:
            print(f"[Filter] 模型回复违规 (类别: {out_flt['category']})，已替换")
            reply = "抱歉，该回复涉及不适宜内容，无法展示。请换个话题试试。"

    # 记录Bot回复
    ctx.add_message(conv_id, Message(
        role="assistant", content=reply,
        username="Bot", user_id="",
        timestamp=datetime.now().isoformat(),
    ))

    # 发送回复
    token = await gateway.get_token()
    await MessageTool.send_reply(session, d, t, reply, token)

    # 压缩检查
    if ctx.get_conversation(conv_id).needs_compress():
        asyncio.create_task(compress_context(conv_id, session))


async def compress_context(conv_id: str, session: aiohttp.ClientSession):
    """压缩对话上下文"""
    prompt = ctx.build_compression_prompt(conv_id)
    original_chars = ctx.get_conversation(conv_id).total_chars

    summary = await llm.chat_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        system="你是一个对话摘要专家，请精确地压缩对话内容。",
        is_compression=True,
    )

    if summary:
        ctx.apply_compression(conv_id, summary, original_chars)
        new_chars = ctx.get_conversation(conv_id).total_chars
        print(f"[Compress] {conv_id}: {original_chars} → {new_chars} 字符")
    else:
        print(f"[Compress] {conv_id}: 压缩失败")


# ============================================================
# 主循环
# ============================================================

async def run():
    global running

    print("=" * 60)
    print("  QBot v2.1 — QQ Bot Agent Framework")
    print(f"  AppID: {QQ_BOT['app_id']}")
    print(f"  默认模型: {MODELS['default']}")
    print(f"  视觉模型: {MODELS['vision']}")
    print(f"  备用模型: {MODELS['fallback']}")
    print(f"  上下文窗口: {CONTEXT['max_chars']:,} 字符")
    print(f"  压缩阈值: {CONTEXT['compress_threshold']:,} 字符")
    print(f"  已注册技能: {', '.join(skill_registry.list_skills())}")
    print("=" * 60)

    while running:
        try:
            async with aiohttp.ClientSession() as session:
                await gateway.connect(handle_event, session)
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