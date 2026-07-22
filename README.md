# QBot v2.1 — QQ Bot Agent Framework

模块化架构的 QQ Bot，参考 Claude Code / Codex / Hermes Agent 设计模式。

## 架构

```
QQ用户 → QQ Bot API (WebSocket) → app.py
                                    ├── qbot/core/gateway.py      → 长连接管理
                                    ├── qbot/core/llm_client.py   → 多模型路由
                                    ├── qbot/memory/context_engine.py → 记忆系统
                                    ├── qbot/tools/message_tools.py   → 图片/消息
                                    └── qbot/skills/channel_skill.py  → 腾讯频道API
```

## 快速开始

```bash
cd ~/research/qqbot-claude-bridge
pip install -r requirements.txt
python app.py
```

## 开机自启动

已复制到 Windows 启动文件夹（`start_bridge.vbs`），开机自动运行。

## 模型路由

| 消息类型 | 模型 | 说明 |
|---------|------|------|
| 纯文本 | HORIZON-DeepSeek-Pro | 默认 |
| 带图片 | HORIZON-MiniMax | 自动下载 → base64 → 视觉识别 |
| 失败回退 | HORIZON-GLM | 自动切换 |

## 上下文工程

- 1M 字符窗口，800K 触发自动压缩
- 无效消息过滤（灌水/表情/重复）
- 用户画像系统（兴趣/关系/风格）
- 压缩后存为 MD 文档归档

## 腾讯频道技能

集成 45 个频道管理 API：
- 频道/版块/成员管理
- 帖子发布/编辑/删除/搜索/置顶/精华
- 评论/回复/点赞
- 私信/通知推送

## 人设

通过 `AGENT.md` 驱动，当前为 ikun 小黑子人设。

## 文件结构

```
qqbot-claude-bridge/
├── app.py                  ← 主入口
├── qbot/                   ← 框架
│   ├── config.py           ← 集中配置
│   ├── core/gateway.py     ← WebSocket 网关
│   ├── core/llm_client.py  ← LLM 多模型路由
│   ├── memory/context_engine.py  ← 记忆系统
│   ├── skills/channel_skill.py   ← 腾讯频道技能
│   └── tools/message_tools.py    ← 图片/消息工具
├── AGENT.md                ← 人设规则
├── data/                   ← 运行时数据
└── logs/                   ← 日志
```

## GitHub

https://github.com/LiuAnclouds/Qbot