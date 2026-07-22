# QQ Bot Bridge v2.0 — 小黑子 I.K.U.N

基于 HORIZON 多模型驱动的 QQ Bot，拥有人设记忆系统、上下文工程和用户画像。

## 架构

```
QQ用户 → QQ Bot API (WebSocket) → bridge.py
                                    ├─ context_engine.py (记忆系统)
                                    ├─ AGENT.md (人设规则)
                                    └─ HORIZON API
                                         ├─ DeepSeek-Pro (文本)
                                         ├─ MiniMax (视觉)
                                         └─ GLM (备用)
```

## 快速开始

```bash
cd ~/research/qqbot-claude-bridge
pip install -r requirements.txt
python -u bridge.py
```

## 开机自启动

以管理员身份运行 PowerShell:

```powershell
.\install_autostart.ps1
```

手动管理:
```powershell
Start-ScheduledTask -TaskName 'QQBotBridge'   # 启动
Stop-ScheduledTask -TaskName 'QQBotBridge'    # 停止
Get-ScheduledTask -TaskName 'QQBotBridge'     # 查看状态
```

## 模型路由

| 消息类型 | 模型 | 说明 |
|---------|------|------|
| 纯文本 | HORIZON-DeepSeek-Pro | 默认，最强文本能力 |
| 带图片 | HORIZON-MiniMax | 唯一支持视觉理解 |
| 主模型失败 | HORIZON-GLM | 自动回退 |
| 上下文压缩 | HORIZON-DeepSeek-Pro | 需要强总结能力 |

## 上下文工程

### 短期记忆
- 每个群聊/私聊独立维护对话上下文
- 窗口上限: 1,000,000 字符 (1M)
- 最多保留 50 轮对话

### 自动压缩
- 上下文达到 800K 字符时自动触发
- 调用 LLM 提取有效信息
- 压缩结果保存为 MD 文档
- 原始上下文被替换为精炼摘要

### 无效过滤
自动过滤以下消息 (不计入上下文):
- 纯表情/符号
- 纯灌水 (哈哈/嗯嗯/666)
- 空白/标点消息

## 用户画像系统

自动追踪每个用户:
- 昵称、聊天次数、关系等级
- 兴趣爱好 (篮球/音乐/游戏/编程/动漫/舞蹈/科技)
- 聊天风格 (简洁型/话痨型/幽默型)
- 重要信息备注

关系升级路线: 陌生人 → 群友 → 朋友 → 老熟人

## 人设 — 小黑子 I.K.U.N

通过 `AGENT.md` 定义:
- 蔡徐坤的铁杆粉丝 (ikun)
- 热爱唱、跳、Rap、篮球
- 说话风趣幽默，适度玩梗
- 正经问题优先认真回答

## 文件结构

```
qqbot-claude-bridge/
├── bridge.py              # 主服务 (WebSocket + LLM路由)
├── context_engine.py      # 上下文引擎 + 用户画像
├── AGENT.md               # 人设规则 (Markdown格式)
├── requirements.txt       # Python依赖
├── start_bridge.bat       # 启动脚本
├── start_bridge.vbs       # 无窗口启动
├── install_autostart.ps1  # 注册开机自启
├── data/
│   ├── conversations/     # 活跃对话上下文
│   ├── profiles/          # 用户画像
│   └── archives/          # 压缩历史 (MD文档)
└── logs/
    └── bridge.log         # 运行日志
```

## 配置项

所有配置在 `bridge.py` 顶部:

- `QQ_BOT_CONFIG` — AppID、AppSecret、API地址
- `HORIZON_CONFIG` — API网关地址和Token
- `MODEL_CONFIG` — 各场景模型选择
- `ALLOWED_GROUP_IDS` — 群白名单

`AGENT.md` — 人设和行为规则 (可随时修改)

## 管理命令

```bash
# 查看运行状态
cat logs/bridge.log

# 查看用户画像
ls data/profiles/

# 查看压缩存档
ls data/archives/

# 停止服务
taskkill /F /IM python.exe  # 或 Ctrl+C

# 清空某个对话上下文
rm data/conversations/<conv_id>.json
```