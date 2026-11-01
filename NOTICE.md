# Attribution and third-party notices

This repository is an independent integration. It is not affiliated with or
endorsed by OpenAI, Tencent/WeChat, or the upstream projects below.

## Dependencies

- **cc-connect** — the WeChat/IM ↔ agent bridge used by this project:
  <https://github.com/chenhg5/cc-connect>. See the upstream project for its
  license and terms.
- **OpenAI Codex CLI / OpenAI API** — the local agent and model provider.
  See OpenAI's terms and pricing.
- **WeChat ilink bot platform** — the messaging gateway. Use it in accordance
  with the platform's terms.

## Design inspiration

The following projects informed the behavior and architecture. No source code
from them is copied, except where explicitly noted.

- **human-chat** (MIT) — conversational style rules were adapted for the
  human-chat persona template: <https://github.com/ElmerAlan-an/human_chat_operit>
- **OpenClaw** — heartbeat, cron, reminders, persistent memory, proactive
  operation: <https://github.com/openclaw/openclaw> (public listing)
- **dsh-proactive** — quiet hours, daily delivery limits, silent wake:
  <https://awesome-dsh-plugin.com/p/john-walks-slow/dsh-proactive--packages-dsh-proactive/>
- **SillyTavern Extension-Idle / Time-Awareness** — idle and probabilistic
  proactive triggers: <https://github.com/SillyTavern/Extension-Idle>,
  <https://github.com/Gu-gu-gu-gu-gu/Time-Awareness>
- **Khoj** — scheduled automations and natural-language reminders:
  <https://github.com/khoj-ai/khoj>
- **Leon** — modular personal-assistant skills and reminders:
  <https://github.com/leon-ai/leon>
- **whalecare** — quiet hours and adaptive proactive pacing:
  <https://pypi.org/project/whalecare/0.1.24/>
- **AstrBot meme_manager** — category-described sticker packs, one-shot send
  probability, and per-session sticker rules informed `sticker_admin.py` and
  `chat_burst.py`: <https://github.com/anka-afk/astrbot_plugin_meme_manager>
- **AstrBot private_companion / LivingMemory** — continuous state, open-thread
  follow-ups, and lightweight recall informed `STATE.md`, `THREADS.md`, and
  `memory_search.py`: <https://github.com/menglimi/astrbot_plugin_private_companion>,
  <https://github.com/lxfight-s-astrbot-plugins/astrbot_plugin_livingmemory>
- **Rho / CompanionBot / Zubo / Pulse / Mercury** — heartbeat and proactive
  agent patterns referenced during design.

## Privacy

The original deployment from which this repository was extracted used a
private persona, private memories, and private bot credentials. Those are not
included. Use the templates under `prompts/` and your own local configuration.
