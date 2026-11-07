#!/usr/bin/env python3
"""Plan one context-driven care opportunity per recipient per day.

Adapted from open-source patterns:
- SillyTavern Time-Awareness: probabilistic proactive triggers
- dsh-proactive / whalecare: daily delivery limit + quiet hours
- cc-connect 1.5: one-shot timers

Rules:
- Plan one opportunity each for master and xi, with randomized times.
- An opportunity is not a mandatory message; missing context still skips.
- Each opportunity is context-gated; proactive messages share a local
  4-message per-recipient local-calendar-day budget and a 5-minute gap.
  This is not a rolling 24-hour quota or a guarantee about server limits. iLink ret=-2 is respected without retry.
- Times are random in 08:30-21:30, at least 2 hours apart.
- No proactive care at 23:00-07:00.
- Each opportunity is only a chance: the agent sends only with real context.
"""
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import care_timer_state as state

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WINDOW_START_MIN = 8 * 60 + 30
WINDOW_END_MIN = 21 * 60 + 30
MIN_GAP_MIN = 120
TARGETS = ("master", "xi")
PLAN_POLICY = "per_recipient_v1"

LEGACY_PROMPT = """【上下文关怀】现在是 {when_text}。今天这是第 {index}/{total} 次随机关怀机会（本地主动消息上限为每位接收者每个本地自然日 4 条、间隔至少 5 分钟；这次最多 2 条）。
请阅读 {work_dir}/PERSONA.md、memory/MEMORY.md、memory/STATE.md、memory/EVENTS.md、memory/THREADS.md 和今天/昨天的原文，判断有没有值得主动关心{master_label}或{partner_label}的事（累了、忙、考试/体测/面试、情绪、久未联系、约定临近、THREADS 里的未完话题）。
如果最近两次主动消息对方都没回，就只回复 NO_REPLY，不要继续发。
如果有，用 python -X utf8 {work_dir}/tools/chat_burst.py master|xi --proactive [--sticker <分类>] "第一句" "第二句" 发 1-2 条；按对象选择 master/xi。表情最多 1 张/天，没有合适的分类就纯文字；如果对方上下文过期就跳过，不要重试、不要报错。
没有真实事由就只回复 NO_REPLY，不要为了发而发。现在如果不在 08:30-21:30，不要发。不要提系统任务。"""


def pick_times(n, now):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Round up so a timer is never less than 30 minutes in the future.
    now_min = now.hour * 60 + now.minute + bool(now.second or now.microsecond)
    start_min = max(WINDOW_START_MIN, now_min + 30)
    if start_min > WINDOW_END_MIN or n <= 0:
        return []
    n = min(n, 1 + (WINDOW_END_MIN - start_min) // MIN_GAP_MIN)
    # Sample compressed time slots, then restore mandatory spacing. This
    # guarantees the gap without a fallback that can violate it late in the day.
    end = WINDOW_END_MIN - (n - 1) * (MIN_GAP_MIN - 1)
    picks = sorted(random.sample(range(start_min, end + 1), n))
    return [
        day + datetime.timedelta(minutes=m + i * (MIN_GAP_MIN - 1))
        for i, m in enumerate(picks)
    ]


CARE_PROMPT = """【上下文关怀】现在是 {when_text}。本次只评估 {target_label}（{target}），不要给另一位发消息。今天每人各有一次评估机会，不保证一定发送。
请阅读 {work_dir}/PERSONA.md，以及共享记忆中与本次对象相关的内容、memory/raw/{sid}/ 今天和昨天的原文、memory/notes/{sid}/ 和未完话题。只使用本对象可知的信息，不透露另一位私下说的话。
优先接续对方最近提过的生活小事、兴趣、好消息或想跟进的话题，不必等到困难或紧急情况才联系；不要编造近况，也不要固定模板问候。
如果最近两次主动消息对方都没回、对方已要求别打扰、过去 30 分钟正在聊天、没有合适话题、上下文过期、账号无法确认或发送状态不明，就只回复 NO_REPLY。不要补发和重试。
如有合适内容，用 python -X utf8 {work_dir}/tools/chat_burst.py {target} --proactive [--sticker <分类>] "一句自然的话" 发送。最多 2 条气泡，图片也算一条；带表情时只发 1 条文字加 1 张合适的表情，不带表情最多 2 条文字。每位接收者仍受已有每日主动额度和间隔限制。
选择表情前读取 assets/stickers/CATEGORIES.md，只用本机已有分类，不编造分类。表情按语境选择，不再额外随机决定是否传入分类。严肃或刚收到坏消息先用文字。脚本提示额度/冷却/发送失败就停止，不换工具重试。
实际执行时间必须在本地 08:30-21:30；不在窗口就只回复 NO_REPLY。不要提系统任务。发送完成后也只回复 NO_REPLY。"""


def recipient_order(day):
    # Rotate the early slot and the only late-day slot fairly across dates.
    return TARGETS if day.toordinal() % 2 == 0 else tuple(reversed(TARGETS))


def new_attempts(now):
    times = pick_times(len(TARGETS), now)
    return [{"at": when.strftime("%Y-%m-%d %H:%M"), "status": "ready", "target": target}
            for target, when in zip(recipient_order(now.date()), times)]


def validate_recipient_plan(plan):
    policy = plan.get("policy")
    if policy is None:
        if any("target" in item for item in plan.get("attempts", [])):
            raise state.StateError("targeted care plan is missing policy version")
        return  # Preserve legacy same-day plans; never backfill or reroll them.
    if policy != PLAN_POLICY:
        raise state.StateError("unknown care policy version")
    attempts = plan.get("attempts")
    if not isinstance(attempts, list) or len(attempts) > len(TARGETS):
        raise state.StateError("invalid per-recipient care plan")
    targets = [item.get("target") for item in attempts]
    if any(target not in TARGETS for target in targets) or len(set(targets)) != len(targets):
        raise state.StateError("invalid or repeated care recipient")


def create_timer(when, index, total, target=None):
    # The existing deployment must independently guarantee that each chosen
    # session resolves to its correct account. A session key is not an account pin.
    if target is not None and target not in TARGETS:
        raise state.NotStarted("invalid care recipient")
    owner = target if target is not None else "master"
    session = getattr(c, "MASTER_SESSION" if owner == "master" else "XI_SESSION", "")
    if not session:
        raise state.NotStarted(f"missing {owner} session")
    iso = when.strftime("%Y-%m-%dT%H:%M")
    if target is None:
        prompt = LEGACY_PROMPT.format(
            when_text=when.strftime("%Y-%m-%d %H:%M"), index=index, total=total,
            work_dir=c.WORK_DIR, master_label=c.LABELS.get("master", "Owner"),
            partner_label=c.LABELS.get("xi", "Partner"))
        description = f"随机关怀 {index}/{total}"
    else:
        prompt = CARE_PROMPT.format(
            when_text=when.strftime("%Y-%m-%d %H:%M"), target=target,
            target_label=c.LABELS.get(target, target), work_dir=c.WORK_DIR,
            sid="s1" if target == "master" else "s2")
        description = f"上下文关怀 {target}"
    return state.add_timer([
        "timer", "add", "--at", iso, "-p", c.PROJECT, "-s", session,
        "--prompt", prompt, "--desc", description,
        "--session-mode", "new_per_run", "--timeout-mins", "30",
    ])


def save_plan(path, plan):
    plan["timers"] = [{"id": item["id"], "at": item["at"]}
                      for item in plan["attempts"] if item["status"] == "scheduled"]
    plan["failed"] = plan["n"] - len(plan["timers"])
    c.save_json_atomic(path, plan)


def plan_day(path, now, is_test=False):
    today = now.date().isoformat()
    absent = object()
    plan = state.read_json(path, absent)
    if plan is not absent:
        state.validate_care_plan(plan, allow_next_day=is_test)
        validate_recipient_plan(plan)
        if plan["date"] > today:
            raise state.StateError("care plan is from the future; check local clock")
        unresolved = any(item["status"] in {"creating", "uncertain"}
                         for item in plan.get("attempts", []))
        legacy_incomplete = ("attempts" not in plan
                             and (plan.get("failed") or len(plan["timers"]) != plan["n"]))
        if plan["date"] != today and (unresolved or legacy_incomplete):
            raise state.StateError("prior care plan is unresolved; preserve it and reconcile timers")
    if plan is absent or plan["date"] != today:
        attempts = ([{"at": (now + datetime.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M"),
                      "status": "ready"}] if is_test else new_attempts(now))
        plan = {"date": today, "n": len(attempts), "timers": [], "failed": len(attempts),
                "attempts": attempts}
        if not is_test:
            plan["policy"] = PLAN_POLICY
        save_plan(path, plan)
    elif not plan.get("failed") and len(plan["timers"]) == plan["n"]:
        print("CARE_ALREADY_PLANNED")
        return 0
    if "attempts" not in plan:
        print("CARE_ALREADY_PLANNED_WITH_FAILURE; reconcile legacy plan before retrying")
        return 1
    if any(item["status"] in {"creating", "uncertain"} for item in plan["attempts"]):
        print("CARE_ALREADY_PLANNED_WITH_FAILURE; reconcile existing timers before retrying")
        return 1
    if not plan["n"]:
        print("CARE_SKIPPED_TODAY")
        return 0
    for index, item in enumerate(plan["attempts"], 1):
        if item["status"] in {"scheduled", "expired"}:
            continue
        when = datetime.datetime.strptime(item["at"], "%Y-%m-%d %H:%M")
        if when < now + datetime.timedelta(minutes=0 if is_test else 30):
            item["status"] = "expired"
            save_plan(path, plan)
            print("CARE_SLOT_EXPIRED; no replacement timer created")
            # A provably unstarted expired slot is terminal for this recipient,
            # not a reason to suppress another still-future ready opportunity.
            continue
        item["status"] = "creating"
        save_plan(path, plan)
        try:
            if "target" in item:
                timer_id, output = create_timer(when, index, plan["n"], target=item["target"])
            else:
                timer_id, output = create_timer(when, index, plan["n"])
        except state.NotStarted as exc:
            item["status"] = "ready"
            save_plan(path, plan)
            print(f"CARE_NOT_STARTED {exc}; fix configuration and retry")
            # This attempt provably never launched. Do not let one unavailable
            # recipient consume the other recipient's independent opportunity.
            continue
        except Exception as exc:
            item["status"] = "uncertain"
            save_plan(path, plan)
            print(f"CARE_ITEM_UNCERTAIN {exc}; reconcile existing timers before retrying")
            return 1
        item.update(id=timer_id, status="scheduled")
        save_plan(path, plan)
        print(f"CARE_PLANNED id={timer_id} at={item['at']} ({index}/{plan['n']})")
    if plan["failed"]:
        print("CARE_PARTIAL_PLAN; unstarted recipients remain ready for safe retry")
        return 1
    return 0


def main():
    now = datetime.datetime.now()
    if "--dry-run" in sys.argv:
        attempts = new_attempts(now)
        print("DRY_RUN n=" + str(len(attempts)) + " opportunities=" + ", ".join(
            item["target"] + "@" + item["at"] for item in attempts))
        return 0
    is_test = "--now" in sys.argv
    # Manual smoke tests keep their own same-day journal, never the real plan.
    path = c.CARE_PLAN_FILE + ".test" if is_test else c.CARE_PLAN_FILE
    try:
        with state.locked(path):
            return plan_day(path, now, is_test)
    except (state.StateError, OSError, ValueError) as exc:
        print(f"CARE_PLAN_FAILED {exc}; inspect existing timers before retrying")
        return 1


if __name__ == "__main__":
    sys.exit(main())
