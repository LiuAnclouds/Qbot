"""
工具模块 — 图片下载、消息解析、回复发送
"""
import asyncio, base64, json, re, io, time
from datetime import datetime
import aiohttp
from ..config import QQ_BOT

# 被动回复的 msg_seq 必须递增且不重复，否则 QQ 返回 40054005 "消息被去重"。
# 用"以毫秒时间戳为起点 + 严格自增"的计数器：起点取当前时间戳保证大于历史值
# (跨重启也不撞去重窗口)，之后严格 +1 保证同毫秒内多次回复也不重复。
_msg_seq_counter = int(time.time() * 1000)


def _next_msg_seq() -> int:
    global _msg_seq_counter
    _msg_seq_counter += 1
    # QQ msg_seq 为 32 位有符号整数，溢出时回绕到一个安全的小值继续递增
    val = _msg_seq_counter % 2147483647
    if val == 0:
        val = 1
    return val


class ImageTool:
    """图片处理工具 — 解决QQ内部CDN图片无法被MiniMax直接访问的问题"""

    @staticmethod
    async def download_as_base64(url: str, session: aiohttp.ClientSession, token: str = None) -> str:
        """下载图片并转为base64 data URL"""
        headers = {}
        if token:
            headers["Authorization"] = f"QQBot {token}"

        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
                    b64 = base64.b64encode(data).decode("ascii")
                    # 诊断: 打印真实下载信息，排查图片格式导致模型"收不到图片"
                    print(f"[ImageTool-Diag] url={url[:90]}")
                    print(f"[ImageTool-Diag] status={resp.status} content_type={content_type} 大小={len(data)} bytes")
                    print(f"[ImageTool-Diag] data_url前缀=data:{content_type};base64,{b64[:40]}...")
                    return f"data:{content_type};base64,{b64}"
                else:
                    print(f"[ImageTool] 下载失败 {resp.status}: {url}")
                    return None
        except Exception as e:
            print(f"[ImageTool] 下载异常: {e}")
            return None

    @staticmethod
    async def download_images(
        urls: list[str], session: aiohttp.ClientSession, token: str = None
    ) -> list[str]:
        """批量下载图片为base64"""
        tasks = [ImageTool.download_as_base64(u, session, token) for u in urls]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]


class MessageTool:
    """消息解析和回复工具"""

    @staticmethod
    def get_conversation_id(payload: dict) -> str:
        if "group_openid" in payload and payload["group_openid"]:
            return f"group_{payload['group_openid']}"
        if "group_id" in payload and payload["group_id"]:
            return f"group_{payload['group_id']}"
        if "guild_id" in payload:
            return f"guild_{payload['guild_id']}_channel_{payload.get('channel_id', '')}"
        return f"user_{payload.get('author', {}).get('id', 'unknown')}"

    @staticmethod
    def extract_message(payload: dict) -> tuple[str, str, dict, list[str]]:
        """返回: (content, conv_id, extra, image_urls)"""
        conv_id = MessageTool.get_conversation_id(payload)
        content = re.sub(r"<@!\d+>", "", payload.get("content", "").strip()).strip()

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

    @staticmethod
    async def send_reply(
        session: aiohttp.ClientSession,
        payload: dict,
        event_type: str,
        text: str,
        token: str,
    ) -> bool:
        """发送回复消息"""
        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

        if event_type == "GROUP_AT_MESSAGE_CREATE":
            group_id = payload.get("group_openid") or payload.get("group_id", "")
            url = f"{QQ_BOT['api_host']}/v2/groups/{group_id}/messages"
            body = {"content": text, "msg_type": 0, "msg_id": payload.get("id"), "msg_seq": _next_msg_seq()}
        elif event_type == "C2C_MESSAGE_CREATE":
            url = f"{QQ_BOT['api_host']}/v2/users/{payload.get('author', {}).get('id', '')}/messages"
            body = {"content": text, "msg_type": 0, "msg_id": payload.get("id"), "msg_seq": _next_msg_seq()}
        elif event_type == "AT_MESSAGE_CREATE":
            url = f"{QQ_BOT['api_host']}/channels/{payload.get('channel_id', '')}/messages"
            body = {"content": text, "msg_id": payload.get("id")}
        else:
            print(f"[Send] 未知消息类型: {event_type}")
            return False

        print(f"[Send] → {url}")
        async with session.post(url, headers=headers, json=body) as resp:
            data = await resp.json()
            print(f"[Send] {resp.status} {json.dumps(data, ensure_ascii=False)[:200]}")
            return resp.status == 200