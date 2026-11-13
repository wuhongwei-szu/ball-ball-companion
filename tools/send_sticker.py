#!/usr/bin/env python3
"""Send one local sticker image to a WeChat bot.

This is the low-level/admin entry. The chat agent should normally use
chat_burst.py, which applies the probability once (default 1.0 for a selected sticker). This module
enforces the configured cooldown and daily cap without another probability gate.

Usage:
    python -X utf8 send_sticker.py master --category happy [--style cat]
    python -X utf8 send_sticker.py xi --category affection --proactive
    python -X utf8 send_sticker.py master --list
"""
import argparse
import datetime
import os
import random
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

try:
    import send_xi
    from send_xi import ILinkError
except Exception:  # pragma: no cover - cryptography should exist on this machine
    send_xi = None
    ILinkError = Exception

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MANIFEST = os.path.join(c.STICKER_DIR, "manifest.json")
COOLDOWN_SECONDS = c.STICKER_COOLDOWN_SECONDS
RECENT_DAYS = 3
MIN_DIM = 240
DEFAULT_STYLES = {
    "master": ("cat", "pig", "silly", "anime", "learned", "generic", "seio"),
    "xi": ("cat", "silly", "anime", "learned", "seio", "generic", "text"),
}


def load_manifest():
    data = c.load_json(MANIFEST, None)
    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list):
        raise SystemExit("表情库为空：请先运行 tools/sticker_admin.py scan")
    return data


def load_usage():
    data = c.local_state.read_json(c.STICKER_USAGE_FILE, {})
    if not isinstance(data, dict):
        raise c.local_state.StateError('invalid sticker usage')
    return data


def load_extra_tags():
    """Semantic tags added in sticker_tags.json (kept separate from scan)."""
    data = c.load_json(os.path.join(c.STICKER_DIR, "sticker_tags.json"), {})
    if not isinstance(data, dict):
        return {}
    return {str(key): [str(tag) for tag in value] for key, value in data.items()
            if isinstance(value, list)}


def target_state(usage, target):
    state = usage.get(target)
    if target not in usage:
        state = {}
        usage[target] = state
    elif not isinstance(state, dict):
        raise c.local_state.StateError('invalid sticker recipient state')
    sent = state.get("sent")
    if 'sent' not in state:
        state["sent"] = []
    elif not isinstance(sent, list) or any(not isinstance(item, dict) for item in sent):
        raise c.local_state.StateError('invalid sticker history')
    return state


def _now():
    return datetime.datetime.now().astimezone()


def _parse_at(value):
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_now().tzinfo)
    return parsed


def _today():
    return _now().strftime("%Y-%m-%d")


def _count_today(sent, proactive=None):
    today = _today()
    count = 0
    for item in sent:
        if not isinstance(item, dict) or not str(item.get("at", "")).startswith(today):
            continue
        if proactive is None or bool(item.get("proactive")) == proactive:
            count += 1
    return count


def _last_sent(sent):
    stamps = [_parse_at(item.get("at", "")) for item in sent if isinstance(item, dict)]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def choose(manifest, category=None, style=None, sticker_id=None):
    stickers = manifest["stickers"]
    if sticker_id:
        matches = [e for e in stickers if e.get("id") == sticker_id]
        if not matches:
            raise SystemExit(f"找不到表情 id: {sticker_id}")
        return matches[0]
    categories = sorted({e["category"] for e in stickers})
    if not category:
        raise SystemExit("需要 --category；可用分类: " + ", ".join(categories))
    pool = [e for e in stickers if e.get("category") == category]
    if not pool:
        raise SystemExit(f"分类 {category} 没有表情；可用分类: " + ", ".join(categories))
    if style:
        styled = [e for e in pool if e.get("style") == style]
        if styled:
            pool = styled
        else:
            print(f"[sticker] 分类 {category} 没有 style={style}，改用同分类其他风格", file=sys.stderr)
    return random.choice(pool)


def _select_candidate(manifest, category, style, sticker_id, state, target, prefer=None):
    base = choose(manifest, category, style, sticker_id)
    if sticker_id:
        return base
    pool = [e for e in manifest["stickers"] if e.get("category") == base.get("category")]
    feedback = c.load_json(os.path.join(c.STICKER_DIR, "feedback.json"), {})
    if isinstance(feedback, dict):
        banned = {sid for sid, fb in feedback.items() if isinstance(fb, dict) and fb.get("banned")}
        pool = [entry for entry in pool if entry["id"] not in banned]
        if not pool:
            return None
    clear = [e for e in pool if min(int(e.get("width", 0)), int(e.get("height", 0))) >= MIN_DIM]
    pool = clear or pool

    # Rotate across the whole emotion category before applying aesthetic preferences.
    last_used = {}
    for item in state.get("sent", []):
        at = _parse_at(item.get("at", ""))
        if at:
            key = item.get("id", "")
            last_used[key] = max(at.timestamp(), last_used.get(key, 0.0))
    cutoff = (_now() - datetime.timedelta(days=RECENT_DAYS)).timestamp()
    fresh = [e for e in pool if last_used.get(e["id"], 0) < cutoff]
    if fresh:
        pool = fresh
    elif len(pool) > 1:
        oldest = min(last_used[e["id"]] for e in pool)
        pool = [e for e in pool if last_used[e["id"]] == oldest]

    if prefer:
        keywords = [k.strip().lower() for k in re.split(r"[,，\s]+", prefer) if k.strip()]
        matched = []
        extra = load_extra_tags()
        for entry in pool:
            tags = list(entry.get("tags", [])) + extra.get(entry.get("id", ""), [])
            haystack = (entry.get("label", "") + " " + " ".join(tags)).lower()
            if any(keyword in haystack for keyword in keywords):
                matched.append(entry)
        if matched:
            pool = matched
        else:
            print(f"[sticker] prefer={prefer} 没有匹配，改用同分类", file=sys.stderr)
    styles = (style,) if style else DEFAULT_STYLES.get(target, ())
    if style or category != "comfort":
        for preferred in styles:
            styled = [e for e in pool if e.get("style") == preferred]
            if styled:
                pool = styled
                break
    return random.choice(pool)


def _send_master(path):
    if not c.MASTER_SESSION:
        raise SystemExit("缺少 master session")
    result = c.run_cc([
        "send", "-p", c.PROJECT, "--session", c.MASTER_SESSION, "--image", path,
    ], timeout=60)
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = error or output or "cc-connect send --image failed"
        print(f"表情发送失败：{detail[:300]}")
        return 1
    print(output or "已发送")
    return 0


def _send_xi(path):
    if send_xi is None:
        print("表情发送失败：缺少 send_xi 模块")
        return 1
    # Choose one transport. A failed/unknown cc-connect result may still mean
    # delivery, so do not fall through to a second send through direct iLink.
    if c.current_target() == "xi" and c.XI_SESSION:
        try:
            first = c.run_cc([
                "send", "-p", c.PROJECT, "--session", c.XI_SESSION,
                "--image", path,
            ], timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            print("表情发送结果未确认（cc-connect 调用异常）；不会切换通道补发，请先核实送达。")
            return 1
        if first.returncode == 0:
            print((first.stdout or "").strip() or "已发送")
            return 0
        print("表情发送结果未确认（cc-connect 返回非零状态）；不会切换通道补发，请先核实送达。")
        return 1
    try:
        send_xi.send_image(path)
    except ILinkError as exc:
        print(f"表情发送失败[{exc.stage}]：{exc.message}")
        return exc.exit_code()
    print("已发送")
    return 0


def _record(target, manifest, entry, proactive):
    usage = load_usage()
    state = target_state(usage, target)
    sent = state.setdefault("sent", [])
    sent.append({
        "id": entry.get("id", ""),
        "category": entry.get("category", ""),
        "style": entry.get("style", ""),
        "at": _now().astimezone().isoformat(timespec="seconds"),
        "proactive": bool(proactive),
    })
    state["sent"] = sent[-100:]
    c.save_json_atomic(c.STICKER_USAGE_FILE, usage)
    sid = "s1" if target == "master" else "s2"
    c.append_raw(sid, f"[表情包:{entry.get('id','')}] {entry.get('category','')}/{entry.get('style','')}")
    c.append_recent(f"[表情包:{entry.get('id','')}]")


@c.outbound_serialized
def send_one(target, category=None, style=None, sticker_id=None,
             proactive=False, force=False, dry_run=False, skip_budget=False, prefer=None):
    """Select, send and record one sticker. Returns 0/-1/3; never raises on send."""
    if target not in {"master", "xi"}:
        print("需要目标 master 或 xi")
        return 1
    c.assert_target(target)
    if proactive and not skip_budget:
        remaining, reason = c.proactive_remaining(target)
        if remaining <= 0:
            print(f"[budget] {reason}；这次不发")
            return 3
    manifest = load_manifest()
    usage = load_usage()
    state = target_state(usage, target)
    sent = state.get("sent", [])
    if c.STICKER_DAILY_LIMIT > 0 and _count_today(sent) >= c.STICKER_DAILY_LIMIT:
        print(f"今天表情额度用完了（{c.STICKER_DAILY_LIMIT}/{c.STICKER_DAILY_LIMIT}），这次只发文字")
        return 3
    if proactive and c.STICKER_PROACTIVE_DAILY_LIMIT > 0 and _count_today(sent, proactive=True) >= c.STICKER_PROACTIVE_DAILY_LIMIT:
        print("今天主动消息的表情额度已用完，这次只发文字")
        return 3
    last = _last_sent(sent)
    if COOLDOWN_SECONDS > 0 and last and not force:
        elapsed = (_now().astimezone() - last.astimezone()).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            print(f"刚发过表情（{int(elapsed)} 秒前），这次先不发")
            return 3

    entry = _select_candidate(manifest, category, style, sticker_id, state, target, prefer)
    if entry is None:
        print("这个分类没有可用表情（可能都被标记为不喜欢）")
        return 3
    path = os.path.join(c.STICKER_DIR, entry["file"])
    if not os.path.isfile(path):
        print(f"表情文件缺失：{entry['file']}")
        return 1
    print(f"[sticker] {entry['id']} {entry['category']}/{entry['style']} {entry['file']}")
    if dry_run:
        return 0

    code = _send_master(path) if target == "master" else _send_xi(path)
    if code == 0:
        _record(target, manifest, entry, proactive)
        c.record_outbound(target, proactive=proactive)
    return code


def main():
    parser = argparse.ArgumentParser(description="发送一张本地表情包")
    parser.add_argument("target", nargs="?", choices=["master", "xi"])
    parser.add_argument("--category")
    parser.add_argument("--style", choices=["cat", "pig", "anime", "seio", "learned", "generic", "text", "silly"])
    parser.add_argument("--id", dest="sticker_id")
    parser.add_argument("--prefer", help="按标签/文字偏好筛选，如 贴贴,抱,合十,击掌")
    parser.add_argument("--proactive", action="store_true")
    parser.add_argument("--force", action="store_true", help="跳过 2 分钟冷却（不跳过每日上限）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        manifest = load_manifest()
        by_cat = {}
        by_style = {}
        for entry in manifest["stickers"]:
            by_cat[entry["category"]] = by_cat.get(entry["category"], 0) + 1
            by_style[entry["style"]] = by_style.get(entry["style"], 0) + 1
        print("categories: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
        print("styles: " + ", ".join(f"{k}={v}" for k, v in sorted(by_style.items())))
        return 0

    return send_one(
        args.target,
        category=args.category,
        style=args.style,
        sticker_id=args.sticker_id,
        proactive=args.proactive,
        force=args.force,
        dry_run=args.dry_run,
        prefer=args.prefer,
    )


if __name__ == "__main__":
    sys.exit(main())
