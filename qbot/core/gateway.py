"""
QQ Bot WebSocket 网关 — 长连接管理
"""
import asyncio, json, time
from datetime import datetime
import aiohttp, aiohttp.http_websocket
from ..config import QQ_BOT


class QQGateway:
    """QQ Bot WebSocket 网关"""

    def __init__(self):
        self.access_token = None
        self.token_expire_at = 0
        self.session_seq = 0
        self.session_id = ""
        self.heartbeat_interval = 41250
        self.ws: aiohttp.ClientWebSocketResponse = None
        self._running = False

    async def get_token(self) -> str:
        if self.access_token and time.time() < self.token_expire_at - 60:
            return self.access_token

        url = QQ_BOT["auth_url"]
        payload = {
            "appId": QQ_BOT["app_id"],
            "clientSecret": QQ_BOT["app_secret"],
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload) as resp:
                data = await resp.json()
                print(f"[Auth] getAccessToken → {json.dumps(data, ensure_ascii=False)}")

        self.access_token = data.get("access_token")
        if not self.access_token:
            raise RuntimeError(f"获取access_token失败: {data}")
        self.token_expire_at = time.time() + int(data.get("expires_in", 7200))
        print(f"[Auth] Token获取成功, 过期: {datetime.fromtimestamp(self.token_expire_at)}")
        return self.access_token

    def build_identify(self) -> dict:
        return {
            "op": 2,
            "d": {
                "token": f"QQBot {self.access_token}",
                "intents": 1 << 25 | 1 << 0,
                "shard": [0, 1],
                "properties": {
                    "$os": "linux",
                    "$browser": "qbot-framework",
                    "$device": "qbot-framework",
                },
            },
        }

    def build_heartbeat(self) -> dict:
        return {"op": 1, "d": self.session_seq}

    async def heartbeat_loop(self):
        interval = self.heartbeat_interval / 1000
        while self._running:
            await asyncio.sleep(interval)
            if self.ws and not self.ws.closed:
                try:
                    await self.ws.send_json(self.build_heartbeat())
                    print(f"[Heartbeat] seq={self.session_seq}")
                except Exception as e:
                    print(f"[Heartbeat] 失败: {e}")
                    break

    async def connect(self, event_handler, session: aiohttp.ClientSession):
        """连接并进入事件循环，event_handler(event, session)"""
        self._running = True
        token = await self.get_token()
        gateway_url = f"wss://{QQ_BOT['gateway_host']}/websocket"

        print(f"[Gateway] 连接 {gateway_url} ...")
        async with session.ws_connect(gateway_url) as ws:
            self.ws = ws
            print("[Gateway] WebSocket已连接")
            await ws.send_json(self.build_identify())
            print("[Gateway] 已发送IDENTIFY")

            hb_task = asyncio.create_task(self.heartbeat_loop())

            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            event = json.loads(msg.data)
                            op = event.get("op")
                            d = event.get("d", {})
                            self.session_seq = event.get("s", self.session_seq)

                            if op == 10:
                                self.heartbeat_interval = d.get("heartbeat_interval", 41250)
                                print(f"[Gateway] HELLO, heartbeat={self.heartbeat_interval}ms")
                            elif op == 0 and event.get("t") == "READY":
                                self.session_id = d.get("session_id", "")
                                print(f"[Gateway] READY! session_id={self.session_id}")
                            elif op == 0 and event.get("t") == "RESUMED":
                                print("[Gateway] RESUME成功 ✓")
                            elif op == 7:
                                print("[Gateway] 服务端要求重连")
                            elif op == 9:
                                print("[Gateway] INVALID_SESSION")
                            else:
                                await event_handler(event, session)

                        except json.JSONDecodeError as e:
                            print(f"[Gateway] JSON解析失败: {e}")
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        print("[Gateway] 连接关闭")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print(f"[Gateway] 错误: {ws.exception()}")
                        break
            finally:
                hb_task.cancel()
                try:
                    await hb_task
                except asyncio.CancelledError:
                    pass

    async def stop(self):
        self._running = False