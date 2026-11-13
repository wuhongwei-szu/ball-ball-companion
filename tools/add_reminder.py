#!/usr/bin/env python3
"""Create a personalized one-shot reminder through cc-connect's timer.

Usage:
    python -X utf8 add_reminder.py --owner master|xi|both \
      --date 2026-11-10 --time 07:30 \
      --title "体测" --note "带水、运动鞋，别迟到"
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import care_timer_state as state

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_index():
    data = state.read_json(c.REMINDERS_INDEX, [])
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise state.StateError("invalid reminder index; preserve it and reconcile timers")
    return data


def save_index(items):
    c.save_json_atomic(c.REMINDERS_INDEX, items)


def build_prompt(owner, when_text, title, note):
    label = c.LABELS.get(owner, owner)
    return f"""【定时提醒】现在是 {when_text}。提醒对象：{label}。事项：{title}。备注：{note}。
请参考 {c.WORK_DIR}/PERSONA.md、memory/MEMORY.md、memory/STATE.md、memory/THREADS.md 和最近原文，用 1-2 条自然的微信短消息提醒对方，结合对方近况，不要模板化，不要提“定时/系统任务”。
用 python -X utf8 {c.WORK_DIR}/tools/chat_burst.py {owner} --proactive [--sticker <分类>] "第一句" "第二句" 发送；事情紧急或严肃时不要加表情；本地主动消息安全上限为每位接收者每个本地自然日 4 条、间隔 5 分钟，按语境自然发。没有合适分类就纯文字。最后只回复 NO_REPLY。"""


def add_one(owner, when, title, note, items):
    sessions = {"master": c.MASTER_SESSION, "xi": c.XI_SESSION}
    if not sessions.get(owner):
        return None, f"missing {owner} session; no timer process started"
    iso = when.strftime("%Y-%m-%dT%H:%M")
    when_text = when.strftime("%Y-%m-%d %H:%M")
    prompt = build_prompt(owner, when_text, title, note)
    item = {
        "owner": owner, "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H:%M"), "title": title, "note": note,
        "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "creating",
    }
    items.append(item)
    save_index(items)
    try:
        timer_id, output = state.add_timer([
            "timer", "add", "--at", iso, "-p", c.PROJECT,
            "-s", sessions[owner], "--prompt", prompt, "--desc", title,
            "--session-mode", "new_per_run", "--timeout-mins", "30",
        ])
    except state.NotStarted:
        # A process was never started, so this recipient may safely retry.
        items.remove(item)
        save_index(items)
        return None, "timer command did not start; fix configuration and retry"
    except Exception:
        item["status"] = "uncertain"
        save_index(items)
        return None, "timer outcome uncertain; reconcile existing timers before retrying"
    item.update(id=timer_id, status="scheduled")
    save_index(items)
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

    owners = ["master", "xi"] if args.owner == "both" else [args.owner]
    try:
        with state.locked(c.REMINDERS_INDEX):
            return create_missing(args, when, owners)
    except (state.StateError, OSError, ValueError) as exc:
        print(f"REMINDER_FAILED {exc}; inspect existing timers before retrying")
        return 1


def create_missing(args, when, owners):
    items = load_index()
    pending = []
    failed = False
    for owner in owners:
        matches = [existing for existing in items if (
            existing.get("owner") == owner
            and existing.get("date") == args.date
            and existing.get("time") == args.time
            and existing.get("title") == args.title
        )]
        if any(item.get("status") in ("creating", "uncertain") for item in matches):
            print(f"提醒创建状态未确认（{owner}）；请先核对已有 timer，不要重试创建。")
            failed = True
        elif any(item.get("status") in ("scheduled", "sent") for item in matches):
            print(f"这个提醒已经存在（{owner}）：{args.date} {args.time} {args.title}")
        else:
            pending.append(owner)

    created = []
    for owner in pending:
        timer_id, output = add_one(owner, when, args.title, args.note, items)
        if not timer_id:
            print(f"记录失败（{owner}）：{output}")
            failed = True
            continue
        created.append((owner, timer_id))

    save_index(items)
    for owner, timer_id in created:
        print(f"REMINDER_OK id={timer_id} owner={owner} at={args.date} {args.time} title={args.title}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
