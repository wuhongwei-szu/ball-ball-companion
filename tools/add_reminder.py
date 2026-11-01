#!/usr/bin/env python3
"""Create a personalized one-shot reminder through cc-connect's timer.

Usage:
    python -X utf8 add_reminder.py --owner master|xi|both \
      --date 2026-11-10 --time 07:30 \
      --title "体测" --note "带水、运动鞋，别迟到"
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_index():
    try:
        with open(c.REMINDERS_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_index(items):
    os.makedirs(os.path.dirname(c.REMINDERS_INDEX), exist_ok=True)
    with open(c.REMINDERS_INDEX, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def build_prompt(owner, when_text, title, note):
    label = c.LABELS.get(owner, owner)
    return f"""【定时提醒】现在是 {when_text}。提醒对象：{label}。事项：{title}。备注：{note}。
请参考 {c.WORK_DIR}/PERSONA.md、memory/MEMORY.md、memory/STATE.md、memory/THREADS.md 和最近原文，用 1-2 条自然的微信短消息提醒对方，结合对方近况，不要模板化，不要提“定时/系统任务”。
用 python -X utf8 {c.WORK_DIR}/tools/chat_burst.py {owner} --proactive [--sticker <分类>] "第一句" "第二句" 发送；事情紧急或严肃时不要加表情；主人要求不设本地表情额度，按语境自然发。没有合适分类就纯文字。最后只回复 NO_REPLY。"""


def add_one(owner, when, title, note, items):
    sessions = {"master": c.MASTER_SESSION, "xi": c.XI_SESSION}
    c.require(sessions.get(owner), f"{owner} session")
    iso = when.strftime("%Y-%m-%dT%H:%M")
    when_text = when.strftime("%Y-%m-%d %H:%M")
    prompt = build_prompt(owner, when_text, title, note)
    result = c.run_cc([
        "timer", "add",
        "--at", iso,
        "-p", c.PROJECT,
        "-s", sessions[owner],
        "--prompt", prompt,
        "--desc", title,
        "--session-mode", "new_per_run",
        "--timeout-mins", "30",
    ])
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        return None, (error or output or "cc-connect timer add failed")
    timer_id = None
    for line in output.splitlines():
        if line.startswith("Timer created:"):
            timer_id = line.split(":", 1)[1].strip()
    if not timer_id:
        return None, f"cannot parse timer id: {output[:200]}"
    items.append({
        "id": timer_id,
        "owner": owner,
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H:%M"),
        "title": title,
        "note": note,
        "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "scheduled",
    })
    return timer_id, output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, choices=["master", "xi", "both"])
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--time", required=True, help="HH:MM")
    parser.add_argument("--title", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--allow-night", action="store_true",
                        help="Allow a reminder during 23:00-07:00")
    args = parser.parse_args()

    try:
        when = datetime.datetime.strptime(args.date + " " + args.time, "%Y-%m-%d %H:%M")
    except ValueError:
        print("时间格式不对，请用 YYYY-MM-DD 和 HH:MM")
        return 1
    if when <= datetime.datetime.now():
        print("时间已经过了，请确认日期和时间后再记录。")
        return 1
    if not args.allow_night and (when.hour >= 23 or when.hour < 7):
        print("这个时间在安静时段（23:00-07:00），建议改到早上；如果确实需要，请加 --allow-night。")
        return 1

    items = load_index()
    owners = ["master", "xi"] if args.owner == "both" else [args.owner]

    for existing in items:
        if (
            existing.get("owner") in owners
            and existing.get("date") == args.date
            and existing.get("time") == args.time
            and existing.get("title") == args.title
            and existing.get("status") in ("scheduled", "sent")
        ):
            print(f"这个提醒已经存在：{existing.get('id')} {args.date} {args.time} {args.title}")
            return 0

    created = []
    for owner in owners:
        timer_id, output = add_one(owner, when, args.title, args.note, items)
        if not timer_id:
            print(f"记录失败（{owner}）：{output}")
            save_index(items)
            return 1
        created.append((owner, timer_id))

    save_index(items)
    for owner, timer_id in created:
        print(f"REMINDER_OK id={timer_id} owner={owner} at={args.date} {args.time} title={args.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
