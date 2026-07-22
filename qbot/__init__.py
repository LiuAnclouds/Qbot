"""
QBot — QQ Bot Agent Framework
=============================
模块化架构:
  core/     → WebSocket 网关、模型路由、LLM 客户端
  memory/   → 上下文引擎、用户画像、压缩器
  skills/   → 技能注册表 (腾讯频道等)
  tools/    → 工具集 (图片下载、消息发送等)
"""
__version__ = "2.1.0"