#!/usr/bin/env python3
"""Inspect and maintain the local reminder index.

The cc-connect timer delivers reminders, but the JSON index only records that
a timer was created. This tool adds a small lifecycle so past reminders do not
stay "scheduled" forever and block a future reminder with the same title.

Usage:
    python -X utf8 tools/reminder_admin.py --list
    python -X utf8 tools/reminder_admin.py --mark <id> --status sent
    python -X utf8 tools/reminder_admin.py --mark <id> --status cancelled
    python -X utf8 tools/reminder_admin.py --gc
"""
import argparse
import datetime
import json
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import care_timer_state as state
import reminder_send

STATUSES = {"scheduled", "sent", "expired", "cancelled", "missed"}


def load():
    try:
        with open(c.REMINDERS_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise state.StateError('invalid reminder index; preserve it for inspection')
        return data
    except FileNotFoundError:
        return []


def save(items):
    c.save_json_atomic(c.REMINDERS_INDEX, items)


def parse_at(item):
    try:
        return datetime.datetime.strptime(
            str(item.get("date", "")) + " " + str(item.get("time", "")),
            "%Y-%m-%d %H:%M",
        )
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description="提醒索引维护")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--mark")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--gc", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    migration = parser.add_mutually_exclusive_group()
    migration.add_argument('--migration-plan', action='store_true', help='validate and show pending timer migration, without writing')
    migration.add_argument('--migrate-stopped', action='store_true', help='migrate the timer file and index only while cc-connect is stopped')
    parser.add_argument('--dispatcher-command', action='store_true', help='print the command for the existing maintenance cron')
    args = parser.parse_args()

    try:
        with state.locked(c.REMINDERS_INDEX):
            return maintain(args, parser)
    except (state.StateError, OSError, ValueError):
        print('提醒状态无法读取或正在修改；本次未变更，请稍后核对。', file=sys.stderr)
        return 1


def maintain(args, parser):
    items = load()
    if args.dispatcher_command:
        print(reminder_send.command())
        return 0
    if args.migration_plan or args.migrate_stopped:
        timer_file = os.path.join(c.DATA_DIR, 'timers', 'jobs.json')
        timers = state.read_json(timer_file, None)
        plan = reminder_send.migration_plan(items, timers)
        if args.migrate_stopped and not args.dry_run:
            require_stopped()
            # Timer commands first: an interrupted migration remains fail-closed
            # in the dispatcher until the index is upgraded by a successful rerun.
            c.save_json_atomic(timer_file, plan['timers'])
            save(plan['index'])
        print(json.dumps({'status':'migrated' if args.migrate_stopped and not args.dry_run else 'plan',
                          'upgraded_ids':plan['upgraded_ids'], 'dispatcher_command':reminder_send.command()}, ensure_ascii=False))
        return 0
    if args.list:
        receipts = state.read_json(c.REMINDERS_INDEX + '.delivery.json', {})
        if not isinstance(receipts, dict):raise state.StateError('invalid reminder delivery journal')
        for item in items:
            group = reminder_send.group_id(item['owner'],item['date'],item['time'])
            delivery = receipts.get(group, {})
            if not isinstance(delivery, dict):raise state.StateError('invalid reminder delivery record')
            print(f"{item.get('id')}\t{item.get('owner')}\t{item.get('date')} {item.get('time')}\t"
                  f"{item.get('status')}\treceipt={delivery.get('status','unverified')}\t{item.get('title')}")
        return 0

    if args.mark:
        if not args.status:
            print("--mark 需要同时给 --status", file=sys.stderr)
            return 2
        found = False
        for item in items:
            if item.get("id") == args.mark:
                if args.status == 'sent':
                    group = reminder_send.group_id(item['owner'], item['date'], item['time'])
                    receipts = state.read_json(c.REMINDERS_INDEX + '.delivery.json', {})
                    record = receipts.get(group, {}) if isinstance(receipts, dict) else None
                    if not isinstance(record,dict) or record.get('status') != 'accepted':
                        print('没有发送接受回执，不能把提醒标为 sent；保留待核对状态。', file=sys.stderr)
                        return 2
                item["status"] = args.status
                item["updated_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
                found = True
                break
        if not found:
            print(f"找不到提醒 {args.mark}", file=sys.stderr)
            return 2
        if not args.dry_run:
            save(items)
        print(f"REMINDER_MARK id={args.mark} status={args.status}")
        return 0

    if args.gc:
        now = datetime.datetime.now()
        receipts = state.read_json(c.REMINDERS_INDEX + '.delivery.json', {})
        if not isinstance(receipts,dict):raise state.StateError('invalid reminder delivery journal')
        changed = []
        for item in items:
            if item.get("status") != "scheduled":
                continue
            when = parse_at(item)
            group = reminder_send.group_id(item['owner'],item['date'],item['time'])
            receipt = receipts.get(group,{})
            if not isinstance(receipt,dict):raise state.StateError('invalid reminder delivery record')
            if receipt.get('status') in {'accepted','sending','uncertain'}:
                continue  # Recovery/reconciliation owns these, never age them into "unsent".
            if when is not None and when + datetime.timedelta(seconds=reminder_send.GRACE_SECONDS) < now:
                # Legacy timer/model completion is not evidence of either sending
                # or missing delivery. Keep that distinction in the index.
                item["status"] = "missed" if item.get('dispatch_version') == reminder_send.VERSION else 'delivery_unverified'
                item["updated_at"] = now.astimezone().isoformat(timespec="seconds")
                changed.append(item.get("id"))
        if changed and not args.dry_run:
            save(items)
        print(f"REMINDER_GC {'DRY-RUN ' if args.dry_run else ''}expired={len(changed)} ids={changed}")
        return 0

    parser.print_help()
    return 0


def require_stopped():
    if os.name != 'nt' or not c.CC_BIN or not os.path.isabs(c.CC_BIN):
        raise state.StateError('automatic stopped-service verification requires the configured Windows executable')
    executable = c.CC_BIN.replace("'", "''")
    command = ("$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process -Filter \"Name='cc-connect.exe'\" "
               "| Where-Object { $_.ExecutablePath -eq '" + executable + "' }).Count")
    result = subprocess.run(['powershell.exe','-NoProfile','-Command',command],
                            capture_output=True, text=True, timeout=15)
    if result.returncode != 0 or result.stdout.strip() != '0':
        raise state.StateError('stop the maintained service and watchdog before migration; unable to prove it is stopped')


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
