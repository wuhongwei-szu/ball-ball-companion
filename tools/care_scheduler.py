#!/usr/bin/env python3
"""Plan 0-3 randomized, context-driven care timers per day.

Adapted from open-source patterns:
- SillyTavern Time-Awareness: probabilistic proactive triggers
- dsh-proactive / whalecare: daily delivery limit + quiet hours
- cc-connect 1.5: one-shot timers

Rules:
- Roll 0-4 opportunities (weights 45/30/15/8/2).
- Some days send nothing; some days may have several.
- No local send quota: the owner asked to remove it. Each opportunity is still
  context-gated, and iLink's own ret=-2 throttle is respected without retry.
- Times are random in 08:30-21:30, at least 2 hours apart.
- No proactive care at 23:00-07:00.
- Each opportunity is only a chance: the agent sends only with real context.
"""
import datetime
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WINDOW_START_MIN = 8 * 60 + 30
WINDOW_END_MIN = 21 * 60 + 30
MIN_GAP_MIN = 120
MAX_TIMERS = 4
WEIGHTS = [45, 30, 15, 8, 2]  # 0, 1, 2, 3, 4 (owner asked for no hard send cap)

PROMPT = """【上下文关怀】现在是 {when_text}。今天这是第 {index}/{total} 次随机关怀机会（主人要求不设发送额度）。
请阅读 {work_dir}/PERSONA.md、memory/MEMORY.md、memory/STATE.md、memory/EVENTS.md、memory/THREADS.md 和今天/昨天的原文，判断有没有值得主动关心{master_label}或{partner_label}的事（累了、忙、考试/体测/面试、情绪、久未联系、约定临近、THREADS 里的未完话题）。
如果最近两次主动消息对方都没回，就只回复 NO_REPLY，不要继续发。
如果有，用 python -X utf8 {work_dir}/tools/chat_burst.py master|xi --proactive [--sticker <分类>] "第一句" "第二句" 发 1-2 条；按对象选择 master/xi。表情最多 1 张/天，没有合适的分类就纯文字；如果对方上下文过期就跳过，不要重试、不要报错。
没有真实事由就只回复 NO_REPLY，不要为了发而发。现在如果不在 08:30-21:30，不要发。不要提系统任务。"""


def pick_times(n, now):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_min = WINDOW_START_MIN
    now_min = now.hour * 60 + now.minute
    if now.date() == day.date():
        start_min = max(start_min, now_min + 30)
    if start_min >= WINDOW_END_MIN or n <= 0:
        return []

    for _ in range(300):
        picks = sorted(random.sample(range(start_min, WINDOW_END_MIN + 1), n))
        if all(picks[i + 1] - picks[i] >= MIN_GAP_MIN for i in range(n - 1)):
            return [day + datetime.timedelta(minutes=m) for m in picks]

    span = WINDOW_END_MIN - start_min
    step = span // n
    return [
        day + datetime.timedelta(minutes=start_min + step * i + random.randint(0, max(0, step - 1)))
        for i in range(n)
    ]


def create_timer(when, index, total):
    c.require(c.MASTER_SESSION, "master_session（从 session 文件推导）")
    iso = when.strftime("%Y-%m-%dT%H:%M")
    prompt = PROMPT.format(
        when_text=when.strftime("%Y-%m-%d %H:%M"),
        index=index,
        total=total,
        work_dir=c.WORK_DIR,
        master_label=c.LABELS.get("master", "Owner"),
        partner_label=c.LABELS.get("xi", "Partner"),
    )
    result = c.run_cc([
        "timer", "add",
        "--at", iso,
        "-p", c.PROJECT,
        "-s", c.MASTER_SESSION,
        "--prompt", prompt,
        "--desc", f"随机关怀 {index}/{total}",
        "--session-mode", "new_per_run",
        "--timeout-mins", "30",
    ])
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        return None, (error or output or "timer add failed")
    timer_id = None
    for line in output.splitlines():
        if line.startswith("Timer created:"):
            timer_id = line.split(":", 1)[1].strip()
    return timer_id, output


def main():
    now = datetime.datetime.now()
    today = now.date().isoformat()

    if "--dry-run" in sys.argv:
        n = random.choices(range(MAX_TIMERS + 1), weights=WEIGHTS)[0]
        times = pick_times(n, now)
        print("DRY_RUN n=" + str(n) + " times=" + ", ".join(t.strftime("%H:%M") for t in times))
        return 0

    is_test = "--now" in sys.argv
    if not is_test:
        try:
            with open(c.CARE_PLAN_FILE, encoding="utf-8") as f:
                plan = json.load(f)
        except Exception:
            plan = {}
        if plan.get("date") == today:
            print("CARE_ALREADY_PLANNED")
            return 0
        n = random.choices(range(MAX_TIMERS + 1), weights=WEIGHTS)[0]
        times = pick_times(n, now)
    else:
        n = 1
        times = [now + datetime.timedelta(minutes=1)]

    if n == 0:
        plan = {"date": today, "n": 0, "timers": [], "note": "no care today"}
        os.makedirs(os.path.dirname(c.CARE_PLAN_FILE), exist_ok=True)
        with open(c.CARE_PLAN_FILE, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print("CARE_SKIPPED_TODAY")
        return 0

    created = []
    for i, when in enumerate(times, 1):
        timer_id, output = create_timer(when, i, n)
        if timer_id:
            created.append({"id": timer_id, "at": when.strftime("%Y-%m-%d %H:%M")})
            print(f"CARE_PLANNED id={timer_id} at={when.strftime('%Y-%m-%d %H:%M')} ({i}/{n})")
        else:
            print(f"CARE_ITEM_FAILED {output}")

    if not is_test:
        plan = {"date": today, "n": n, "timers": created}
        os.makedirs(os.path.dirname(c.CARE_PLAN_FILE), exist_ok=True)
        with open(c.CARE_PLAN_FILE, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
