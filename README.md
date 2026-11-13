# Ball Ball Companion

当前稳定版：[v0.3.1](https://github.com/wuhongwei-szu/ball-ball-companion/releases/tag/v0.3.1) · [更新日志](CHANGELOG.md)

一个可自托管的微信 AI 陪伴机器人：**两个微信 bot、共享人格与长期记忆、自然多气泡、表情包、一次性提醒、上下文关怀**。

项目由 cc-connect 1.5.x 桥接微信，Codex CLI 作为本地 agent，模型可配置（示例部署使用 `gpt-6.1-sol`，reasoning `low`）。
仓库只包含通用代码、模板和文档；**不包含任何 token、openid、API key、聊天记忆或私人配置**。

## 特性

| 能力 | 说明 |
|---|---|
| 完整语音理解 | 保留微信转写和完整原音，音频模型听语气与停顿，现有球球继续回复；复用附件、语音环境与官方 SDK |
| 双 bot 共享人格 | 两个微信 bot 共用同一份 persona 与长期记忆，各自保留对话笔记；`whoami.py` 明确当前通道 |
| 会话查询 | `view_session.py` 按 openid 找最近活跃会话，不再硬编码 s1/s2 |
| 多气泡聊天 | 用 `chat_burst.py` 发 1-3 条短消息并带自然停顿，最后用 `NO_REPLY` 抑制多余回复 |
| 表情包 | 本地分类图库；`comfort` 安慰分类 + `sticker_tags.json` 语义标签；脚本按概率、冷却、每日上限决定发不发 |
| 事件提醒 | 说“下周二体测”，确认日期后用 cc-connect 内置 `timer` 到点提醒 |
| 提醒维护 | `reminder_admin.py` 查询、标记、清理过期提醒状态 |
| 随机关怀 | 每天每位接收者各一次评估机会，按上下文决定是否发送；08:30-21:30，每人每自然日 4 条主动消息的本地预算 |
| 长期记忆 | 原文捕获 → 助手生成记录归档（送达未核实） → 每晚整理 → `MEMORY.md` / `STATE.md` / `EVENTS.md` / `THREADS.md` |
| 当前事实 | `companion_memory.py` 的 `current_fact` 带来源/版本；检索按当前通道优先，跨人事实只在明确提到对方时注入 |
| 核心记忆 | `config/core_memory.json` 常驻稳定偏好；每轮优先注入当前人的 active 版本，避免旧偏好被闲聊挤掉 |
| 事实权重/有效期 | `importance + access_count + 30 天衰减` 自动降权旧事实；time-bound 事实用 `--valid-until`，每日 `expire` 自动失效 |
| `/usage` Platform 行 | [账单时段补丁](deploy/cc-connect-usage-freshness.patch) 显示 UTC 查询范围、已返回费用与最后金额结果日；配置见 [docs/CC_CONNECT_USAGE_PATCH.md](docs/CC_CONNECT_USAGE_PATCH.md) |
| 每周反思 | 每周日生成 `memory/WEEKLY.md`，评估主动关怀与待改进点；`CARE_LOG.md` 记录已发主动消息；`IMPROVEMENTS.md` 维护低风险自我改进清单 |
| 微信纯文本 | `send_msg.py` / `chat_burst.py` 发送前清理 `**`、标题、反引号和代码围栏 |
| 反重复 | 最近 20 条回复写入 `recent_replies.md`，新会话读取以避免重复 |
| 安全 | 原文写入前自动脱敏；`allow_from` 限制使用者；私有配置 gitignore |
| 运维 | 隐藏自启、5 分钟看门狗、每日轻量 + 每周完整备份、日志轮转、只读健康检查 |

## 架构

```text
WeChat ilink bot A ─┐
                    ├─ cc-connect 1.5.x ─ Codex CLI ─ OpenAI (configurable)
WeChat ilink bot B ─┘         │
                              ├─ crons: 记忆整理 / 原文回填 / 提醒清理 / 每周反思 / 关怀规划
                              ├─ timers: 一次性提醒、随机关怀
                              └─ webhook / management API (optional)

work_dir/
├── AGENTS.md                  # 行为规则（由 prompts/AGENTS.template.md 渲染）
├── PERSONA.md                 # 人格（由 prompts/PERSONA.template.md 渲染）
├── memory/
│   ├── MEMORY.md              # 共享长期记忆
│   ├── STATE.md               # 心情/精力/关系温度/小日常
│   ├── EVENTS.md              # 重要日子与约定
│   ├── THREADS.md             # 未完话题与约定（主动关心素材）
│   ├── WEEKLY.md              # 每周反思（每周任务生成）
│   ├── IMPROVEMENTS.md        # 自我改进清单（低风险直接做，规则改动只提议）
│   ├── CARE_LOG.md            # 已发送的主动关怀记录
│   ├── companion.sqlite3      # 带来源/版本的 current_fact
│   ├── sticker_usage.json     # 表情发送历史/每日额度
│   ├── raw/s1|s2/             # 对话原文（自动脱敏，含助手生成记录归档（送达未核实））
│   ├── notes/s1|s2/           # 每日笔记
│   ├── reminders.json         # 已创建提醒索引
│   ├── recent_replies.md      # 最近 20 条回复
│   └── .care_plan.json        # 当天随机关怀计划
├── assets/stickers/           # 本地表情库（不入公开仓库）
└── tools/
    ├── common.py              # 配置加载、会话/token 推导、微信纯文本清洗
    ├── whoami.py              # 输出当前通道 master/xi
    ├── view_session.py        # 按 openid 查看最近活跃会话
    ├── chat_burst.py          # 统一的多气泡 + 表情发送入口
    ├── send_sticker.py        # 选图/额度/冷却 + 发送一张表情
    ├── sticker_admin.py       # 表情库 scan/validate/list/catalog/import
    ├── sticker_tag.py         # 表情语义标签维护（--auto/--set/--list）
    ├── sticker_review.py      # 生成表情图鉴 PDF/CSV/HTML（优先使用 .venv-review）
    ├── send_tts.py            # Edge TTS 生成晓晓语音 MP3 并以文件发送
    ├── memory_search.py       # 本地记忆关键词检索
    ├── companion_memory.py    # 有来源的共同记忆（bridge/search/learn）
    ├── send_msg.py            # 单条发送 + 写原文
    ├── send_xi.py             # 直连第二个 bot 的 ilink API（文本/图片）
    ├── add_reminder.py        # 创建一次性提醒（复用 cc-connect timer）
    ├── reminder_admin.py      # 提醒查询、标记和过期清理
    ├── care_scheduler.py      # 每人每天一次上下文评估
    ├── capture_transcripts.py # 捕获新对话
    ├── capture_runtime.py     # 保守捕获/回填状态
    ├── capture_review.py      # 归档助手生成记录，送达未核实
    ├── healthcheck.py
    ├── backup.ps1
    └── setup_tasks.ps1
```

## 环境要求

- Windows 10/11（部署脚本以 PowerShell 为主）
- Python 3.11+
- Python 依赖见 `requirements.txt`；完整原音理解复用 Python 3.12 语音环境中的 `openai` 与 `silk-python`。`cryptography`（第二个 bot 发图必需）；`Pillow`（表情库缩图可选）；`edge-tts`（可选语音，建议用 Python 3.12 独立 venv）
- cc-connect **1.5.x**（示例使用 1.5.0）
- Codex CLI（桌面版自带或 `npm install -g @openai/codex`）
- 两个微信 ilink bot（cc-connect 的 `weixin` 平台）
- OpenAI API key（模型在 `.codex/config.toml` 配置，示例 `gpt-6.1-sol`）

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
   - `master_account_id` / `xi_account_id`：两个不同的稳定 bot 账号，不能靠配置顺序选账号
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

8. **安装依赖及看门狗与备份任务（可选）**

   ```powershell
   python -m pip install -r requirements.txt
   powershell -ExecutionPolicy Bypass -File tools\setup_tasks.ps1 -BotRoot C:\ai-companion
   ```

9. **健康检查**

   ```bash
   python -X utf8 tools/healthcheck.py
   ```

## 使用

### 多条短消息与表情

机器人优先用 `chat_burst.py` 发 1-3 条短消息，中间随机停顿；可在最后附一张本地表情：

```bash
python -X utf8 tools/chat_burst.py master --sticker affection \
  "主人，辛苦啦～" "今天是不是又忙了一整天？(｡•́︿•̀｡)"
```

- 示例采用安全区：每 bot 每天最多 12 张表情、30 秒冷却；每位接收者的主动消息共享本地自然日 4 条、间隔 5 分钟的预算（本地保护设置，不是微信官方配额）。`0` 可关闭某一项，但 iLink 服务端仍可能以 `ret=-2` 节流。
- 图片是独立出站消息，和文字一起计入条数上限（最多 3 条文字 + 1 张表情）。
- 无合适分类、本地安全上限、刚发过时只发文字；不要重试。
- 简单确认或严肃说明用单条 `send_msg.py`，不要硬拆。

### 表情库

表情素材只放本地，不进入公开仓库。首次使用：

```bash
python -X utf8 tools/sticker_admin.py scan
python -X utf8 tools/sticker_admin.py validate
python -X utf8 tools/sticker_admin.py list
```

用 `import` 导入自己的图库；用 `catalog` 生成分类说明。扫描会跳过小于 240px 或小于 20KB 的图，避免发出糊图。
`send_xi.py --image` 直连第二个 bot 的 iLink 媒体上传，避免 cc-connect 多 bot 路由到错误的账号。

### 完整语音输入与晓晓输出

完整原音通过现有附件链路保留，`listen_audio.py` 使用 `gpt-audio-1.5` 听内容、语气和停顿，再由当前主模型结合对话回应。微信现有转写继续使用，不另建转写服务。现有语音 Python 3.12 环境安装 `requirements.txt` 即可复用；细节见 [架构](docs/ARCHITECTURE.md#original-voice-input)。

公开录音的实际 API 调用和完整附件字节链路已验证；手机微信入站仍需实测。

原生语音气泡会被 iLink 拒绝（`ret=-1`），所以语音以 **MP3 文件**发送。准备一个独立的 Python 3.12 环境：

```bash
uv venv .venv-voice --python 3.12
uv pip install --python .venv-voice\Scripts\python.exe edge-tts
```

在 `bot.config.json` 配置 `edge_tts_python`、`edge_tts_voice`（默认 `zh-CN-XiaoxiaoNeural`）、`edge_tts_rate` / `edge_tts_pitch` / `edge_tts_volume`（默认 `-8%` / `+5Hz` / `-5%`）和 `voice_dir`，然后：

```bash
python -X utf8 tools/send_tts.py master "主人，晚安，做个好梦～"
python -X utf8 tools/send_tts.py xi "小主人，球球在呢～" --proactive
```

主动语音加 `--proactive`，占主动消息安全预算；用户明确要求的回复不加。Edge TTS 失败时降级文字，不要改用难听的备用音色。

### 事件提醒

```bash
python -X utf8 tools/add_reminder.py --owner master \
  --date 2026-11-10 --time 07:30 \
  --title "体测" --note "带水、运动鞋，别迟到"
```

底层使用 cc-connect 1.5 的 `timer add --at ...`，到点触发 agent，个性化发送。
23:00-07:00 默认拒绝；明确需要时加 `--allow-night`。

### 随机关怀

`care_scheduler.py` 每天 08:17 为 master 和 xi 各规划一次上下文评估，随机安排在 08:30-21:30、间隔至少两小时。评估只接续真实近况：有内容才发，已闭环事项不催，近期正在聊天或连续两次主动消息未获回复时跳过。保留当前积极使用表情的风格，按情绪选图。

每位接收者的主动发送入口共用本地自然日 4 条预算、间隔至少 5 分钟；每次最多两条，图片算一条。普通回复不占主动预算。这是本地保护设置，不是滚动 24 小时或微信官方配额。遇到网关拒绝停止，不重复试发。

cc-connect v1.5.0 默认本地发送保护也会计入普通回复。示例使用 `burst_limit=20`、`burst_window_secs=60` 保留短时保护。

### 记忆

`capture_transcripts.py` 每 5 分钟捕获新消息到 `memory/raw/`；`capture_review.py`
只归档有来源的 `assistant_unverified` 范围，并标注“会话生成记录，送达未核实”；历史 baseline 缺口保留，不把生成当作已送达。每晚 03:17 的 `memcons01`
整理到 `MEMORY.md` / `EVENTS.md` / `STATE.md` / `THREADS.md`，并用
`companion_memory.py learn --curator` 写入带来源的 `current_fact`。每周日 03:30
生成 `memory/WEEKLY.md` 并更新未完话题。需要旧细节时用 `memory_search.py "关键词"`
检索；跨人事实只在当前消息明确提到对方时注入。所有写入前自动脱敏。
详见 [docs/MEMORY_SYSTEM.md](docs/MEMORY_SYSTEM.md)。

### 用量与余额

- `/usage` 返回的是 **ChatGPT 订阅**额度、窗口已用比例和重置时间。
- `python -X utf8 tools/usage_report.py` 会同时返回 ChatGPT 订阅信息；配置 `OPENAI_ADMIN_KEY`（需要 `api.usage.read`）后，统计 UTC 自然月内 API 已返回的费用，处理完整分页，分别显示查询时段、最后含金额结果日、最后返回桶与抓取时间。
- 空日桶不代表该日费用已经完整返回。配置额度减去已返回费用只称“参考差额”，不当作 Pro 账期余额；官方额度与账期仍以 Platform 为准。
- Admin key 放在 `config/openai_admin.env` 或环境变量里，不要提交；示例见 `config/openai_admin.env.example`。
- 可选旧 credit 接口需要浏览器 session key，默认不配置；没有时只展示已返回费用与配置参考差额。Go 补丁与 Python 缓存格式必须配套，旧缓存会提示刷新。
- 微信里金额写 `14.59 美元` 或 `usd 14.59`，不要写 `$14.59`（PowerShell 会把 `$14` 当变量）。

## 隐私与安全

- **不提交**：bot token、openid、API key、聊天记录、日志、session、备份、`config/bot.config.json`、本地表情素材/生成图片（`assets/`、`artifacts/`）。
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
默认仅准备改动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_to_github.ps1 `
  -Source C:\ai-companion -Repo . -Message "Update companion tools"
```

它使用明确的通用文件清单，拒绝覆盖不同的本地修改；默认只准备 diff，不暂存、提交或推送。审阅后显式加 `-Publish` 才发布，且扫描精确暂存内容、检查 Git 退出状态。memory、真实 config、日志与 token 不在清单内。

## 已测试环境

- Windows 11
- cc-connect 1.5.0
- Codex CLI 0.166 (MSIX desktop)
- OpenAI（模型可配置，示例 `gpt-6.1-sol`）
- 两个微信 ilink bot

## Troubleshooting

- **“⏳ 消息发送过快，请稍后再试”** — cc-connect's per-session incoming rate limit
  (default 20 messages / 60 seconds). For a trusted single-user deployment set
  `[rate_limit] max_messages = 0` in `config.toml`, or wait a minute.
- **“send budget exhausted”** — cc-connect local send guard, including normal replies in v1.5.0.
  Configure each Weixin platform with `burst_limit=20` and `burst_window_secs=60`; do not re-login
  the bot. Each recipient has one daily care evaluation; proactive tools share a per-recipient calendar-day budget of four messages. iLink may still reject a send.
- **“no stored context_token”** — the recipient must message that bot first;
  WeChat does not allow a bot to start a conversation.
- **表情只出现文字/完全没发** — 检查 `sticker_admin.py validate`、每日上限/冷却，以及
  `sticker_usage.json`；iLink 没有原生表情气泡，GIF 是否动图取决于微信端，不能保证。
- **第二个 bot 发图失败** — `send_xi.py` 需要该用户最近给 bot 发过消息；`ret=-2`
  可能是节流，不要重试；等对方再发一条消息或稍后再试。
- **图片太大** — 图库导入会跳过 >2MB 的图；用 `sticker_admin.py scan` 重新校验。

## License

MIT — see [LICENSE](LICENSE). Attribution and design references: [NOTICE.md](NOTICE.md).


The local quota regression is tracked in [upstream issue #1742](https://github.com/chenhg5/cc-connect/issues/1742). A generated response in history is not proof of delivery. API content rejection, local quota failure, and accepted-but-not-visible gateway delivery are separate outcomes.

## 本轮体检与能力边界

体检与修复见 [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md)。开源依赖、借鉴方案及尚未接入的部分见 [docs/OPEN_SOURCE_INTEGRATIONS.md](docs/OPEN_SOURCE_INTEGRATIONS.md)。共享记忆的引擎侧接入依赖维护版 cc-connect；仅安装官方 npm 包不能复现全部定制能力，见 [源码核对](docs/source-reconciliation.md)。
