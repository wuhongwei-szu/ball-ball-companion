# Ball Ball Companion

一个可自托管的微信 AI 陪伴机器人：**两个微信 bot、共享人格与长期记忆、多条短消息、一次性提醒、随机关怀**。

项目由 cc-connect 1.5.x 桥接微信，Codex CLI 作为本地 agent，默认使用 `gpt-6-luna`。
仓库只包含通用代码、模板和文档；**不包含任何 token、openid、API key、聊天记忆或私人配置**。

## 特性

| 能力 | 说明 |
|---|---|
| 双 bot 共享人格 | 两个微信 bot 共用同一份 persona 与长期记忆，各自保留对话笔记 |
| 多气泡聊天 | 用 `send_msg.py` 逐条发送 2-3 条短消息，最后用 `NO_REPLY` 抑制多余回复 |
| 事件提醒 | 说“下周二体测”，确认日期后用 cc-connect 内置 `timer` 到点提醒 |
| 随机关怀 | 每天随机 0-2 次机会（55/32/13），时间在 08:30-21:30，23:00-07:00 安静；关怀上限 2 次；本地发送预算使用短窗口 |
| 长期记忆 | 原文捕获 → 每晚整理 → `MEMORY.md` / `STATE.md` / `EVENTS.md` |
| 反重复 | 最近 20 条回复写入 `recent_replies.md`，新会话读取以避免重复 |
| 安全 | 原文写入前自动脱敏；`allow_from` 限制使用者；私有配置 gitignore |
| 运维 | 隐藏自启、5 分钟看门狗、每日备份、日志轮转、只读健康检查 |

## 架构

```text
WeChat ilink bot A ─┐
                    ├─ cc-connect 1.5.x ─ Codex CLI ─ OpenAI (gpt-6-luna)
WeChat ilink bot B ─┘         │
                              ├─ crons: 每日要闻 / 记忆整理 / 原文捕获 / 关怀规划
                              ├─ timers: 一次性提醒、随机关怀
                              └─ webhook / management API (optional)

work_dir/
├── AGENTS.md                  # 行为规则（由 prompts/AGENTS.template.md 渲染）
├── PERSONA.md                 # 人格（由 prompts/PERSONA.template.md 渲染）
├── memory/
│   ├── MEMORY.md              # 共享长期记忆
│   ├── STATE.md               # 心情/精力/关系温度
│   ├── EVENTS.md              # 重要日子与约定
│   ├── raw/s1|s2/             # 对话原文（自动脱敏）
│   ├── notes/s1|s2/           # 每日笔记
│   ├── reminders.json         # 已创建提醒索引
│   ├── recent_replies.md      # 最近 20 条回复
│   └── .care_plan.json        # 当天随机关怀计划
└── tools/
    ├── common.py              # 配置加载与会话/token 运行时推导
    ├── send_msg.py            # 逐条发送 + 写原文
    ├── send_xi.py             # 直连第二个 bot 的 ilink API
    ├── add_reminder.py        # 创建一次性提醒（复用 cc-connect timer）
    ├── care_scheduler.py      # 每天规划 0-3 次随机关怀
    ├── capture_transcripts.py # 捕获新对话
    ├── healthcheck.py
    ├── backup.ps1
    └── setup_tasks.ps1
```

## 环境要求

- Windows 10/11（部署脚本以 PowerShell 为主）
- Python 3.11+
- cc-connect **1.5.x**（示例使用 1.5.0）
- Codex CLI（桌面版自带或 `npm install -g @openai/codex`）
- 两个微信 ilink bot（cc-connect 的 `weixin` 平台）
- OpenAI API key（默认模型 `gpt-6-luna`）

## 快速开始

1. **安装 cc-connect 与 Codex**

   ```bash
   npm install -g cc-connect@1.5.0
   npm install -g @openai/codex   # 或使用 Codex 桌面版
   ```

2. **创建工作目录并克隆仓库**

   ```bash
   mkdir C:\ai-companion
   git clone https://github.com/wuhongwei-szu/ball-ball-companion.git C:\ai-companion
   ```

3. **配置两个微信 ilink bot**

   复制 `config/config.example.toml` 到 `%USERPROFILE%\.cc-connect\config.toml`，
   填入两个 bot 的 token、account_id 与 `allow_from`。不要把真实值提交到仓库。

4. **设置 API key**

   复制 `.env.example` 为 `.env`（或在系统环境变量中设置 `OPENAI_API_KEY`）。
   `config.example.toml` 使用 `${OPENAI_API_KEY}` 环境变量替换。

5. **生成本地 bot 配置**

   复制 `config/bot.config.example.json` 到 `config/bot.config.json`（该文件已被
   gitignore），填写：

   - `work_dir`：工作目录
   - `cc_data_dir`、`cc_config_file`
   - `session_file`：`%USERPROFILE%\.cc-connect\sessions\my-project_<hash>.json`
   - `master_session_id` / `xi_session_id`：通常是 `s1` / `s2`
   - `xi_platform_index`：第二个 weixin 平台在配置中的序号（默认 2）
   - `bot_name` / `labels`

   `bot.config.json` 不保存 token 或 openid；脚本运行时从 cc-connect 配置和
   session 文件读取。

6. **渲染人格与规则模板**

   将 `prompts/PERSONA.template.md`、`prompts/AGENTS.template.md` 复制到工作目录为
   `PERSONA.md`、`AGENTS.md`，替换 `{{...}}` 占位符。也可以用任何模板引擎渲染。

7. **启动 cc-connect**

   - 如果 `codex` 已在 PATH，直接运行 `cc-connect --config "%USERPROFILE%\.cc-connect\config.toml"`。
   - 如果使用 Windows MSIX 桌面版，编译 `deploy/codex_wrapper.c` 到 `bin\codex.exe`，
     用 `deploy/start_cc.example.bat` 模板设置 `CC_CODEX_REAL` 与 PATH。
   - 详细步骤见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

8. **安装看门狗与每日备份（可选）**

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\setup_tasks.ps1 -BotRoot C:\ai-companion
   ```

9. **健康检查**

   ```bash
   python -X utf8 tools/healthcheck.py
   ```

## 使用

### 多条短消息

机器人用 `send_msg.py` 逐条发送，最后回复 `NO_REPLY`：

```bash
python -X utf8 tools/send_msg.py master "主人，辛苦啦～"
python -X utf8 tools/send_msg.py master "今天是不是又忙了一整天？(｡•́︿•̀｡)"
python -X utf8 tools/send_msg.py master "先喝点水，球球陪你歇一会儿 🌙"
```

### 事件提醒

```bash
python -X utf8 tools/add_reminder.py --owner master \
  --date 2026-11-10 --time 07:30 \
  --title "体测" --note "带水、运动鞋，别迟到"
```

底层使用 cc-connect 1.5 的 `timer add --at ...`，到点触发 agent，个性化发送。
23:00-07:00 默认拒绝；明确需要时加 `--allow-night`。

### 随机关怀

`care_scheduler.py` 每天 08:17 规划 0-2 次机会（55/32/13），时间随机在
08:30-21:30，间隔至少 2 小时。每次机会只是“可以关心”，agent 判断有真实
上下文才发，否则 `NO_REPLY`。因此某天可能 0 条，某天可能两条。

cc-connect v1.5.0 默认的本地发送保护会把普通回复也计入四条/24小时预算。
示例配置改为 burst_limit=20、burst_window_secs=60，保留短时保护。
这不是微信官方每日额度；遇到网关拒绝应记录错误并停止重试。关怀上限仍为 2 次。

### 记忆

`capture_transcripts.py` 每 5 分钟捕获新消息到 `memory/raw/`；每晚 03:17 的
`memcons01` 整理到 `MEMORY.md` / `EVENTS.md` / `STATE.md`。所有写入前自动脱敏。
详见 [docs/MEMORY_SYSTEM.md](docs/MEMORY_SYSTEM.md)。

## 隐私与安全

- **不提交**：bot token、openid、API key、聊天记录、日志、session、备份、`config/bot.config.json`。
- 私有值只存在 `%USERPROFILE%\.cc-connect\` 和本地 `config/bot.config.json`。
- `common.py` 在运行时从 cc-connect 配置和 session 文件推导 token/openid，**不落盘**。
- `capture_transcripts.py` / `send_msg.py` 写入前做密钥/token/密码脱敏。
- 仓库自带 `scripts/secret_scan.py`，CI 也会运行。
- 详见 [docs/PRIVACY.md](docs/PRIVACY.md)。

## 仓库结构

```text
config/      配置示例（无真实值）
prompts/     AGENTS / PERSONA 模板
tools/       通用脚本
deploy/      启动脚本模板与 Codex 转发器源码
scripts/     密钥扫描、同步脚本
docs/        架构、部署、记忆、提醒、隐私
```

## 更新与发布

`scripts/sync_to_github.ps1` 从工作目录同步通用工具到本仓库，运行密钥扫描，
然后提交并推送：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_to_github.ps1 `
  -Source C:\ai-companion -Repo . -Message "Update companion tools"
```

它只复制 `tools/*.py`、`tools/*.ps1` 和 `deploy/codex_wrapper.c`，不会复制
memory、config、日志或 token。

## 已测试环境

- Windows 11
- cc-connect 1.5.0
- Codex CLI 0.166 (MSIX desktop)
- OpenAI `gpt-6-luna`
- 两个微信 ilink bot

## Troubleshooting

- **“⏳ 消息发送过快，请稍后再试”** — cc-connect's per-session incoming rate limit
  (default 20 messages / 60 seconds). For a trusted single-user deployment set
  `[rate_limit] max_messages = 0` in `config.toml`, or wait a minute.
- **“send budget exhausted”** — cc-connect local send guard, including normal replies in v1.5.0.
  Configure each Weixin platform with `burst_limit=20` and `burst_window_secs=60`; do not re-login
  the bot. Care is capped at 2/day by default.
- **“no stored context_token”** — the recipient must message that bot first;
  WeChat does not allow a bot to start a conversation.

## License

MIT — see [LICENSE](LICENSE). Attribution and design references: [NOTICE.md](NOTICE.md).


The local quota regression is tracked in [upstream issue #1742](https://github.com/chenhg5/cc-connect/issues/1742). A generated response in history is not proof of delivery. API content rejection, local quota failure, and accepted-but-not-visible gateway delivery are separate outcomes.
