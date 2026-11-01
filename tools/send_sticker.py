#!/usr/bin/env python3
"""Send one local sticker image to a WeChat bot.

This is the low-level/admin entry. The chat agent should normally use
chat_burst.py, which enforces the 1/3 probability, cooldown, and daily cap.

Usage:
    python -X utf8 send_sticker.py master --category happy [--style cat]
    python -X utf8 send_sticker.py xi --category affection --proactive
    python -X utf8 send_sticker.py master --list
"""
import argparse
import datetime
import os
import random
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
    "master": ("cat", "pig", "silly", "anime", "generic", "seio"),
    "xi": ("cat", "silly", "anime", "seio", "generic", "text"),
}


def load_manifest():
    data = c.load_json(MANIFEST, None)
    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list):
        raise SystemExit("表情库为空：请先运行 tools/sticker_admin.py scan")
    return data


def load_usage():
    data = c.load_json(c.STICKER_USAGE_FILE, {})
    return data if isinstance(data, dict) else {}


def target_state(usage, target):
    state = usage.get(target)
    if not isinstance(state, dict):
        state = {}
        usage[target] = state
    sent = state.get("sent")
    if not isinstance(sent, list):
        state["sent"] = []
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


def _recent_ids(sent):
    cutoff = _now() - datetime.timedelta(days=RECENT_DAYS)
    ids = set()
    for item in sent:
        if not isinstance(item, dict):
            continue
        at = _parse_at(item.get("at", ""))
        if at and at >= cutoff:
            ids.add(item.get("id", ""))
    return ids


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


def _select_candidate(manifest, category, style, sticker_id, state, target):
    base = choose(manifest, category, style, sticker_id)
    if sticker_id:
        return base
    pool = [e for e in manifest["stickers"] if e.get("category") == base.get("category")]
    if style:
        styled = [e for e in pool if e.get("style") == style]
        if styled:
            pool = styled
    else:
        for preferred in DEFAULT_STYLES.get(target, ()):
            styled = [e for e in pool if e.get("style") == preferred]
            if styled:
                pool = styled
                break
    clear = [e for e in pool if min(int(e.get("width", 0)), int(e.get("height", 0))) >= MIN_DIM]
    if clear:
        pool = clear
    recent = _recent_ids(state.get("sent", []))
    fresh = [e for e in pool if e.get("id") not in recent]
    pool = fresh or pool
    # Prefer stickers not used recently; randomize among the oldest half.
    last_used = {}
    for item in state.get("sent", []):
        if isinstance(item, dict):
            at = _parse_at(item.get("at", ""))
            if at:
                key = item.get("id", "")
                last_used[key] = max(at.timestamp(), last_used.get(key, 0.0))
    pool.sort(key=lambda e: last_used.get(e.get("id", ""), 0.0))
    head = pool[: max(1, min(8, len(pool)))]
    return random.choice(head)


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


def send_one(target, category=None, style=None, sticker_id=None,
             proactive=False, force=False, dry_run=False):
    """Select, send and record one sticker. Returns 0/-1/3; never raises on send."""
    if target not in {"master", "xi"}:
        print("需要目标 master 或 xi")
        return 1
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

    entry = _select_candidate(manifest, category, style, sticker_id, state, target)
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
    return code


def main():
    parser = argparse.ArgumentParser(description="发送一张本地表情包")
    parser.add_argument("target", nargs="?", choices=["master", "xi"])
    parser.add_argument("--category")
    parser.add_argument("--style", choices=["cat", "pig", "anime", "seio", "generic", "text", "silly"])
    parser.add_argument("--id", dest="sticker_id")
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
    )


if __name__ == "__main__":
    sys.exit(main())
