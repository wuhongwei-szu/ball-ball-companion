#!/usr/bin/env python3
"""Deterministic, receipt-accounted reminder batches. No model and no resend on uncertainty."""
import argparse
import copy
import datetime
import hashlib
import json
import os
import shlex
import sys

import common as c
import care_timer_state as state

VERSION = 1
GRACE_SECONDS = 60 * 60


def group_id(owner, day, clock):
    if owner not in {'master', 'xi'}:
        raise state.StateError('unknown reminder recipient')
    when = datetime.datetime.strptime(day + ' ' + clock, '%Y-%m-%d %H:%M')
    if when.strftime('%Y-%m-%d %H:%M') != day + ' ' + clock:
        raise state.StateError('noncanonical reminder time')
    return owner + ':' + day + 'T' + clock


def command(owner=None, day=None, clock=None):
    args = [getattr(c, 'CFG', {}).get('reminder_python') or sys.executable, '-X', 'utf8',
            os.path.join(c.WORK_DIR, 'tools', 'reminder_send.py')]
    if owner is None:
        args += ['--due']
    else:
        group_id(owner, day, clock)
        args += [owner, '--date', day, '--time', clock]
    if os.name != 'nt':
        return shlex.join(args)
    # The maintained Windows timer executes PowerShell -Command, not cmd.exe.
    # Single-quoted literals preserve spaces, $, %, and shell metacharacters.
    return '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in args) + '; exit $LASTEXITCODE'


def read_index():
    items = state.read_json(c.REMINDERS_INDEX, [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise state.StateError('invalid reminder index; preserve it')
    return items


def send_via_cc(owner, text):
    session = c.MASTER_SESSION if owner == 'master' else c.XI_SESSION
    if not session:
        return {'outcome': 'not_sent', 'basis': 'missing_session'}
    account = c.CFG.get(owner + '_account_id')
    bound_account = getattr(c, 'MASTER_BOT_ACCOUNT' if owner == 'master' else 'XI_BOT_ACCOUNT', '')
    if not isinstance(account,str) or not account or account != bound_account:
        return {'outcome':'not_sent','basis':'account_binding_unavailable'}
    args = ['send', '-p', c.PROJECT, '--session', session, '--account', account,
            '-m', c.sanitize_wechat(text)]
    if not c.CC_BIN:
        return {'outcome': 'not_sent', 'basis': 'missing_executable'}
    try:
        args = c._cc_account_args(args)
    except (ValueError, SystemExit):
        return {'outcome': 'not_sent', 'basis': 'account_binding_unavailable'}
    # run_cc pins the stable account before launching. Never switch transports.
    try:
        result = c.run_cc(args, timeout=60)
    except FileNotFoundError:
        return {'outcome': 'not_sent', 'basis': 'executable_not_found'}
    if result.returncode == 0 and (result.stdout or '').strip() == 'Message sent successfully.':
        return {'outcome': 'accepted', 'basis': 'cc_exit_zero_and_success_ack'}
    return {'outcome': 'uncertain', 'basis': 'cc_result_unconfirmed'}


def _account(owner, group, now):
    # The receipt ID and counter are one atomic write under the ordinary send lock.
    # Recovery after a crash can repeat accounting without repeating the transport.
    budget, entry = c._outbound_entry(owner)
    accepted_day = now.date().isoformat()
    if accepted_day != c._local_now().date().isoformat():
        entry = budget[owner].setdefault(accepted_day, {'proactive':0, 'replies':0, 'last_proactive':''})
    receipts = entry.get('reminder_receipts', [])
    if not isinstance(receipts, list) or any(not isinstance(value, str) for value in receipts):
        raise state.StateError('invalid reminder receipt counters')
    if group not in receipts:
        entry['proactive'] = int(entry.get('proactive', 0)) + 1
        previous = entry.get('last_proactive')
        if previous:
            try:
                previous = datetime.datetime.fromisoformat(previous)
                if previous.tzinfo is None:previous = previous.replace(tzinfo=now.tzinfo)
            except (TypeError,ValueError):
                raise state.StateError('invalid last proactive timestamp') from None
        if not previous or previous < now:
            entry['last_proactive'] = now.isoformat(timespec='seconds')
        entry['reminder_receipts'] = receipts + [group]
        c.save_json_atomic(c.OUTBOUND_STATE_FILE, budget)


def _text(owner, items):
    lines = [c.LABELS.get(owner, owner) + '，到时间啦：']
    for item in items:
        title, note = item.get('title'), item.get('note', '')
        if not isinstance(title, str) or not title.strip() or not isinstance(note, str):
            raise state.StateError('invalid reminder content; preserve the index')
        lines.append('• ' + title + ('；' + note if note else ''))
    return '\n'.join(lines)


def _fingerprints(items):
    return sorted(hashlib.sha256(json.dumps({key:item.get(key) for key in
                  ('owner','date','time','title','note','created_at')}, sort_keys=True,
                  ensure_ascii=False).encode('utf-8')).hexdigest() for item in items)


def _sticker_category(items):
    if any(item.get('urgent') is True or item.get('text_only') is True for item in items):
        return None
    return items[0].get('sticker_category') or c.CFG.get('reminder_sticker_category') or 'work'


def _try_sticker(owner, group, items, journal, path, *, just_accepted):
    record = journal[group]
    if record.get('sticker_status') != 'ready':return
    try:
        # Recovery finishes the text receipt only; it never introduces a late image.
        category = record.get('sticker_category')
        now = c._local_now()
        _, entry = c._outbound_entry(owner)
        reserved = set()
        for item in items:
            if item.get('owner') != owner or item.get('status') != 'scheduled':continue
            if item.get('date') != now.date().isoformat():continue
            when = datetime.datetime.strptime(item['date']+' '+item['time'],'%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
            other = group_id(owner,item['date'],item['time'])
            if other != group and when + datetime.timedelta(seconds=GRACE_SECONDS) >= now:
                reserved.add(other)
        available = c.PROACTIVE_DAILY_LIMIT - int(entry.get('proactive',0))
        if not just_accepted or not category:
            record['sticker_status'] = 'skipped_recovery' if not just_accepted else 'text_only'
        elif c.PROACTIVE_DAILY_LIMIT > 0 and available <= len(reserved):
            record['sticker_status'] = 'reserved_for_reminder_text'
        else:
            # Match chat_burst's selected-sticker default probability (1.0).
            # The ordinary image quotas/cooldown still run in send_one. Its gap
            # check is skipped for this same burst, after reserving text budgets.
            record['sticker_status'] = 'attempting'
            c.save_json_atomic(path,journal)
            import send_sticker
            try:
                result = send_sticker.send_one(owner,category=category,proactive=True,skip_budget=True)
            except (Exception,SystemExit):
                record['sticker_status'] = 'uncertain'
            else:
                record['sticker_status'] = 'accepted' if result == 0 else ('skipped' if result == 3 else 'uncertain')
        c.save_json_atomic(path,journal)
    except (Exception,SystemExit):
        # Text receipt/index/counter are already durable. Image bookkeeping must
        # never turn them into a failure or another permission to send the text.
        print('REMINDER_TEXT_ACCEPTED; optional sticker state requires inspection',file=sys.stderr)


def dispatch(owner, day, clock, *, now=None, sender=None):
    now = now or c._local_now()
    group = group_id(owner, day, clock)
    due = datetime.datetime.strptime(day + ' ' + clock, '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
    journal_path = c.REMINDERS_INDEX + '.delivery.json'
    with state.locked(c.REMINDERS_INDEX):
        items = read_index()
        batch = [item for item in items if item.get('owner') == owner
                 and item.get('date') == day and item.get('time') == clock
                 and item.get('status') in {'scheduled','sent'}]
        if not batch or any(item.get('dispatch_version') != VERSION for item in batch):
            return {'status': 'legacy', 'group': group}
        journal = state.read_json(journal_path, {})
        if not isinstance(journal, dict):
            raise state.StateError('invalid reminder delivery journal')
        record = journal.get(group, {})
        if not isinstance(record, dict):
            raise state.StateError('invalid reminder delivery record')
        status = record.get('status')
        if status in {'sending', 'uncertain'}:
            record['status'] = 'uncertain'
            journal[group] = record
            c.save_json_atomic(journal_path, journal)
            return {'status': 'uncertain', 'group': group}
        if status == 'missed':
            return {'status': 'missed', 'group': group}
        if status not in {None, 'blocked', 'accepted'}:
            raise state.StateError('unknown reminder delivery state')
        if status == 'accepted' and record.get('items') != _fingerprints(batch):
            raise state.StateError('accepted reminder contents changed; inspect rather than resend')
        if status != 'accepted' and any(item.get('status') == 'sent' for item in batch):
            raise state.StateError('sent reminder is missing its receipt; never resend')
        if status != 'accepted' and now < due:
            return {'status': 'not_due', 'group': group}
        if status != 'accepted' and now > due + datetime.timedelta(seconds=GRACE_SECONDS):
            journal[group] = {'status': 'missed', 'reason': 'delivery_window_elapsed'}
            for item in batch:item['status'] = 'missed'
            c.save_json_atomic(journal_path, journal)
            c.save_json_atomic(c.REMINDERS_INDEX, items)
            return {'status': 'missed', 'group': group}
        if status != 'accepted' and (now.hour >= 23 or now.hour < 7) and not all(item.get('allow_night') is True for item in batch):
            journal[group] = {'status':'blocked', 'reason':'quiet_hours'}
            c.save_json_atomic(journal_path, journal)
            return {'status':'blocked', 'group':group}
        try:
            with c.local_state.locked(c.OUTBOUND_STATE_FILE, reentrant=True):
                just_accepted = False
                if status != 'accepted':
                    # The stored reminder's recipient is the explicit relay target.
                    # A maintenance cron may be bound to the other bot's session.
                    c.assert_target(owner, relay=True)
                    remaining, _ = c.proactive_remaining(owner)
                    if remaining <= 0:
                        journal[group] = {'status': 'blocked', 'reason': 'proactive_budget_or_gap'}
                        c.save_json_atomic(journal_path, journal)
                        return {'status': 'blocked', 'group': group}
                    text = _text(owner, batch)
                    journal[group] = {'status': 'sending', 'attempted_at': now.isoformat(),
                                      'items': _fingerprints(batch),
                                      'sticker_category':_sticker_category(batch), 'sticker_status':'ready'}
                    c.save_json_atomic(journal_path, journal)
                    try:
                        receipt = (sender or send_via_cc)(owner, text)
                    except Exception:
                        receipt = {'outcome': 'uncertain', 'basis': 'transport_exception'}
                    outcome = receipt.get('outcome') if isinstance(receipt, dict) else None
                    if outcome != 'accepted':
                        status = 'blocked' if outcome == 'not_sent' else 'uncertain'
                        journal[group].update(status=status, reason='not_started' if status == 'blocked' else 'unconfirmed_send')
                        c.save_json_atomic(journal_path, journal)
                        return {'status': status, 'group': group}
                    journal[group].update(status='accepted', receipt_basis=receipt.get('basis', 'accepted'),
                                          accepted_at=c._local_now().isoformat())
                    c.save_json_atomic(journal_path, journal)
                    just_accepted = True
                accepted_at = datetime.datetime.fromisoformat(journal[group]['accepted_at'])
                _account(owner, group, accepted_at)
                if 'archive_status' not in journal[group]:
                    journal[group]['archive_status'] = 'writing'
                    c.save_json_atomic(journal_path, journal)
                    try:
                        text = _text(owner, batch)
                        c.append_raw('s1' if owner == 'master' else 's2', text,
                                     'assistant', journal[group]['accepted_at'])
                        c.append_recent(text, journal[group]['accepted_at'])
                        c.append_care_log(owner, text)
                    except Exception:
                        journal[group]['archive_status'] = 'uncertain'
                    else:
                        journal[group]['archive_status'] = 'ok'
                    c.save_json_atomic(journal_path, journal)
                for item in batch:
                    item.update(status='sent', delivery_basis=journal[group]['receipt_basis'],
                                accepted_at=journal[group]['accepted_at'])
                c.save_json_atomic(c.REMINDERS_INDEX, items)
                _try_sticker(owner,group,items,journal,journal_path,just_accepted=just_accepted)
                return {'status': 'accepted', 'group': group}
        except c.local_state.StateBusy:
            # No transport began. The minute dispatcher can retry within the window.
            return {'status': 'blocked', 'group': group}


def migration_plan(items, timers, *, now=None):
    """Build a complete validated migration in memory; caller must stop the service before saving."""
    now = now or c._local_now()
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise state.StateError('invalid reminder index')
    if not isinstance(timers, list) or any(not isinstance(t, dict) for t in timers):
        raise state.StateError('invalid timer store')
    if len({t.get('id') for t in timers}) != len(timers):
        raise state.StateError('ambiguous timer ids')
    output, jobs = copy.deepcopy(items), copy.deepcopy(timers)
    by_id = {job.get('id'): job for job in jobs}
    upgraded = []
    for item in output:
        if item.get('status') != 'scheduled':continue
        try:
            group = group_id(item.get('owner'),item.get('date'),item.get('time'))
            due = datetime.datetime.strptime(item['date'] + ' ' + item['time'], '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
        except (TypeError, ValueError):
            raise state.StateError('invalid scheduled reminder identity/date') from None
        if due <= now:continue
        if (due.hour >= 23 or due.hour < 7) and item.get('allow_night') is not True:
            raise state.StateError('night reminder requires explicit allow_night confirmation before migration')
        owner = item['owner']
        if not isinstance(item.get('id'),str) or not item['id']:
            raise state.StateError('scheduled reminder is missing its timer id')
        job = by_id.get(item.get('id'))
        session = c.MASTER_SESSION if owner == 'master' else c.XI_SESSION
        account = c.CFG.get(owner + '_account_id')
        if (not isinstance(job, dict) or job.get('project') != c.PROJECT
                or not session or job.get('session_key') != session
                or not account or job.get('platform_account') != account
                or job.get('fired') is not False
                or job.get('execution_state', '') not in {'', 'pending', 'scheduled'}):
            raise state.StateError('future reminder identity/state does not match its timer')
        stamp = datetime.datetime.fromisoformat(job.get('scheduled_at', '').replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.astimezone(now.tzinfo) != due:
            raise state.StateError('future reminder date does not match its timer')
        executable = command(owner, item['date'], item['time'])
        if job.get('exec') and job['exec'] != executable:
            raise state.StateError('timer already has a different executable')
        job.update(prompt='', exec=executable, mute=True)
        item.update(dispatch_version=VERSION, dispatch_group=group)
        upgraded.append(item['id'])
    return {'index': output, 'timers': jobs, 'upgraded_ids': sorted(set(upgraded))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('owner', nargs='?', choices=['master','xi'])
    parser.add_argument('--date'); parser.add_argument('--time')
    parser.add_argument('--due', action='store_true')
    args = parser.parse_args(argv)
    if not args.due and not (args.owner and args.date and args.time):
        parser.error('provide owner, --date and --time, or --due')
    if args.due and (args.owner or args.date or args.time):
        parser.error('--due cannot be combined with a specific reminder group')
    try:
        now = c._local_now()
        if args.due:
            groups = sorted({(i.get('owner'),i.get('date'),i.get('time')) for i in read_index()
                             if i.get('dispatch_version') == VERSION
                             and i.get('status') in {'scheduled','sent'}
                             and i.get('date','') + ' ' + i.get('time','') <= now.strftime('%Y-%m-%d %H:%M')})
        else:groups = [(args.owner,args.date,args.time)]
        results = [dispatch(*group, now=now) for group in groups]
        print(json.dumps({'reminder_dispatch':results}, ensure_ascii=False))
        return 1 if any(r['status'] in {'uncertain','missed'} for r in results) else 0
    except (state.StateError, OSError, ValueError):
        print('REMINDER_DISPATCH_BLOCKED: inspect local state; no automatic resend', file=sys.stderr)
        return 1


if __name__ == '__main__':sys.exit(main())
