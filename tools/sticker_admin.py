#!/usr/bin/env python3
"""Build and validate the local sticker library.

The library lives under assets/stickers (private, never synced to GitHub).
Usage:
    python -X utf8 sticker_admin.py scan
    python -X utf8 sticker_admin.py validate
    python -X utf8 sticker_admin.py list
    python -X utf8 sticker_admin.py catalog
    python -X utf8 sticker_admin.py import --source DIR --pack NAME [--style generic]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is present on this machine
    Image = None

MANIFEST = os.path.join(c.STICKER_DIR, "manifest.json")
CATALOG = os.path.join(c.STICKER_DIR, "CATEGORIES.md")
IMAGE_EXTS = {".gif", ".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 2 * 1024 * 1024
MIN_BYTES = 20 * 1024
MIN_DIM = 240
MAX_DIM = 800
STYLES = {"cat", "pig", "anime", "seio", "learned", "generic", "text", "silly"}

CATEGORY_DESCRIPTIONS = {
    "happy": "开心、庆祝、积极反馈、好消息",
    "angry": "生气、抗议、玩笑式威胁；不用于真实冲突",
    "sad": "难过、委屈、失落、道歉、求安慰",
    "confused": "疑惑、不理解、需要澄清",
    "surprised": "震惊、意外、被吓到",
    "shy": "害羞、脸红、撒娇、不好意思",
    "sleep": "困倦、晚安、休息",
    "tired": "疲惫、摆烂、没精神",
    "affection": "喜欢、亲昵、贴贴、安慰、感谢",
    "comfort": "安慰、抱抱、贴贴、摸头、合十、击掌、拍拍",
    "food": "吃饭、零食、馋、投喂",
    "greeting": "早安、晚安、打招呼、欢迎",
    "work": "工作、加班、忙碌、摸鱼",
    "entertainment": "游戏、唱歌、娱乐、玩梗",
    "teasing": "吐槽、调侃、自嘲、坏笑、沙雕",
    "reply": "普通回应、倾听、等待",
    "meow": "卖萌、猫猫、可爱互动",
    "morning": "早安专用",
    "baka": "轻微责备、可爱型抱怨",
    "sigh": "无奈、无语、感慨",
    "see": "偷瞄、关注、观察",
    "like": "喜欢某个事物、点赞",
    "refusal": "拒绝、不行、不同意",
}

PACK_STYLES = {
    "official-001": "generic",
    "seio": "seio",
    "bluefish": "silly",
    "chinesebqb": "generic",
    "learned-master": "learned",
    "learned-xi": "learned",
}

STYLE_LABELS = {
    "cat": "猫猫",
    "pig": "猪猪",
    "anime": "可爱二次元",
    "seio": "蓝发二次元（少量）",
    "learned": "学到的表情",
    "generic": "通用",
    "text": "文字梗",
    "silly": "大肥鱼/沙雕",
}


def _label_from_path(path):
    stem = Path(path).stem
    # ChineseBQB: 是喵星人啦00080-击掌猫 -> 击掌猫; 猪00012-睡了 -> 睡了
    cleaned = re.sub(r"^.*?\d{3,}[-_ ]*", "", stem)
    # SEIO/bluefish: 058_得分(10分) -> 得分(10分)
    cleaned = re.sub(r"^\d+[-_ ]*", "", cleaned)
    cleaned = cleaned.replace("_", " ").strip(" -_")
    if not cleaned or re.fullmatch(r"[0-9a-fA-Fx]+", cleaned):
        return ""
    if re.fullmatch(r"s\d+-\d+", cleaned, re.I) or re.fullmatch(r"file\s*\d+", cleaned, re.I):
        return ""
    return cleaned[:24]


def _tags_for(entry, label, animated):
    tags = [entry["category"], entry["style"], entry["source"]]
    tags.append("动图" if animated else "静态")
    if label:
        for token in re.split(r"[^\w一-鿿]+", label):
            token = token.strip()
            if len(token) >= 2 and token not in tags:
                tags.append(token)
    return tags[:8]


def _rel(path, root):
    return Path(path).relative_to(root).as_posix()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_info(path):
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            return im.width, im.height, (im.format or "").upper()
    except Exception:
        return None


def _maybe_shrink(path):
    """Shrink oversized static images in place. GIFs are left untouched."""
    if Image is None:
        return
    try:
        with Image.open(path) as im:
            fmt = (im.format or "").upper()
            if fmt == "GIF" or max(im.width, im.height) <= MAX_DIM:
                return
            im.thumbnail((MAX_DIM, MAX_DIM))
            save_kwargs = {}
            if fmt == "JPEG":
                im = im.convert("RGB")
                save_kwargs = {"quality": 85, "optimize": True}
            elif fmt == "PNG":
                save_kwargs = {"optimize": True}
            im.save(path, format=fmt, **save_kwargs)
    except Exception:
        return


def _infer_meta(path, root):
    parts = _rel(path, root).split("/")
    pack = parts[0] if parts else "unknown"
    category = parts[1] if len(parts) > 1 else "reply"
    if category not in CATEGORY_DESCRIPTIONS:
        category = "reply"
    style = PACK_STYLES.get(pack.lower(), "generic")
    if pack.lower() == "chinesebqb":
        sub = parts[1].lower() if len(parts) > 1 else ""
        if sub == "cat":
            style = "cat"
            category = "meow"
        elif sub == "pig":
            style = "pig"
            category = "teasing"
    if category == "meow" and style == "generic":
        style = "cat"
    return pack, category, style


def _iter_images(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.startswith("_")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                yield os.path.join(dirpath, name)


def scan():
    os.makedirs(c.STICKER_DIR, exist_ok=True)
    entries = []
    seen = set()
    skipped = []
    for path in _iter_images(c.STICKER_DIR):
        rel = _rel(path, c.STICKER_DIR)
        if rel.split("/")[0].startswith("_"):
            continue
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            skipped.append((rel, f"{size // 1024}KB > 2MB"))
            continue
        if size < MIN_BYTES:
            skipped.append((rel, f"{size // 1024}KB < 20KB (blurry)"))
            continue
        info = _image_info(path)
        if info is None:
            skipped.append((rel, "unreadable image"))
            continue
        _maybe_shrink(path)
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            skipped.append((rel, f"{size // 1024}KB > 2MB after resize"))
            continue
        info = _image_info(path) or info
        if min(info[0], info[1]) < MIN_DIM:
            skipped.append((rel, f"{info[0]}x{info[1]} below {MIN_DIM}px"))
            continue
        digest = _sha256(path)
        if digest in seen:
            skipped.append((rel, "duplicate sha256"))
            continue
        seen.add(digest)
        pack, category, style = _infer_meta(path, c.STICKER_DIR)
        animated = os.path.splitext(path)[1].lower() == ".gif"
        label = _label_from_path(path) or (
            f"学习的表情·{digest[:4]}" if pack.startswith("learned-") else f"官方·{digest[:4]}"
        )
        entry = {
            "id": f"{pack}_{digest[:8]}",
            "file": rel,
            "category": category,
            "category_label": CATEGORY_DESCRIPTIONS[category],
            "style": style,
            "style_label": STYLE_LABELS.get(style, style),
            "label": label,
            "source": pack,
            "format": info[2].lower(),
            "animated": animated,
            "width": info[0],
            "height": info[1],
            "bytes": size,
            "sha256": digest,
            "added_at": datetime.now().strftime("%Y-%m-%d"),
        }
        entry["tags"] = _tags_for(entry, label, animated)
        entries.append(entry)
    entries.sort(key=lambda e: (e["category"], e["style"], e["id"]))
    counts = {}
    for entry in entries:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    manifest = {
        "version": 2,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "categories": {
            key: {"description": desc, "count": counts.get(key, 0)}
            for key, desc in CATEGORY_DESCRIPTIONS.items()
            if counts.get(key)
        },
        "stickers": entries,
    }
    c.save_json_atomic(MANIFEST, manifest)
    write_catalog(manifest)
    print(f"SCAN_OK stickers={len(entries)} categories={len(manifest['categories'])} skipped={len(skipped)}")
    for rel, reason in skipped[:10]:
        print(f"  skip {rel}: {reason}")
    return 0


def load_manifest():
    data = c.load_json(MANIFEST, None)
    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list):
        raise SystemExit("manifest 不存在或格式不对，请先运行 scan")
    return data


def validate():
    manifest = load_manifest()
    errors = []
    ids = set()
    files = set()
    for entry in manifest["stickers"]:
        sid = entry.get("id", "")
        rel = entry.get("file", "")
        if not sid or sid in ids:
            errors.append(f"bad/duplicate id: {sid!r}")
        ids.add(sid)
        if rel in files:
            errors.append(f"duplicate file: {rel}")
        files.add(rel)
        path = os.path.join(c.STICKER_DIR, rel)
        if not os.path.isfile(path):
            errors.append(f"missing file: {rel}")
            continue
        if entry.get("category") not in CATEGORY_DESCRIPTIONS:
            errors.append(f"bad category: {entry.get('category')!r} ({rel})")
        if entry.get("style") not in STYLES:
            errors.append(f"bad style: {entry.get('style')!r} ({rel})")
        if os.path.getsize(path) > MAX_BYTES:
            errors.append(f"too large: {rel}")
        if os.path.getsize(path) < MIN_BYTES:
            errors.append(f"likely blurry (<20KB): {rel}")
        if min(int(entry.get("width", 0)), int(entry.get("height", 0))) < MIN_DIM:
            errors.append(f"too small: {rel}")
    print(f"VALIDATE {'OK' if not errors else 'FAILED'} stickers={len(manifest['stickers'])} errors={len(errors)}")
    for error in errors[:20]:
        print("  " + error)
    return 0 if not errors else 1


def list_stickers():
    manifest = load_manifest()
    by_cat = {}
    by_style = {}
    for entry in manifest["stickers"]:
        by_cat[entry["category"]] = by_cat.get(entry["category"], 0) + 1
        by_style[entry["style"]] = by_style.get(entry["style"], 0) + 1
    print("categories: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())))
    print("styles: " + ", ".join(f"{k}={v}" for k, v in sorted(by_style.items())))
    print(f"total={len(manifest['stickers'])}")
    return 0


def write_catalog(manifest=None):
    manifest = manifest or load_manifest()
    counts = {}
    for entry in manifest["stickers"]:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    lines = [
        "# 表情包分类",
        "",
        "> 由 `sticker_admin.py` 生成。agent 只需按分类选择，不需要看具体图片。",
        "",
    ]
    for key, desc in CATEGORY_DESCRIPTIONS.items():
        n = counts.get(key, 0)
        if n:
            lines.append(f"- **{key}**（{n} 张）：{desc}")
    styles = sorted({entry.get("style", "") for entry in manifest["stickers"] if entry.get("style")})
    lines += [
        "",
        "风格：" + " / ".join(styles),
        "",
        "使用：`python -X utf8 tools/chat_burst.py master|xi --sticker <分类> ...`",
        "表情由脚本按概率、冷却和每日上限决定发不发；无合适候选时不发。",
        "",
    ]
    with open(CATALOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"CATALOG_OK {CATALOG}")


def import_dir(source, pack, style, default_category):
    source = os.path.abspath(source)
    if not os.path.isdir(source):
        raise SystemExit(f"source 不是目录: {source}")
    if style not in STYLES:
        raise SystemExit(f"style 必须是 {sorted(STYLES)}")
    dest_root = os.path.join(c.STICKER_DIR, pack)
    copied = 0
    skipped = 0
    for path in _iter_images(source):
        rel = _rel(path, source)
        first = rel.split("/")[0] if "/" in rel else default_category
        category = first if first in CATEGORY_DESCRIPTIONS else default_category
        if os.path.getsize(path) > MAX_BYTES:
            skipped += 1
            continue
        info = _image_info(path)
        if info is None:
            skipped += 1
            continue
        digest = _sha256(path)
        dest_dir = os.path.join(dest_root, category)
        os.makedirs(dest_dir, exist_ok=True)
        name = os.path.basename(path)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            if _sha256(dest) == digest:
                skipped += 1
                continue
            stem, ext = os.path.splitext(name)
            dest = os.path.join(dest_dir, f"{stem}_{digest[:8]}{ext}")
        shutil.copy2(path, dest)
        copied += 1
    print(f"IMPORT copied={copied} skipped={skipped} -> {dest_root}")
    return scan()


def main():
    parser = argparse.ArgumentParser(description="本地表情库管理")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    sub.add_parser("validate")
    sub.add_parser("list")
    sub.add_parser("catalog")
    imp = sub.add_parser("import")
    imp.add_argument("--source", required=True)
    imp.add_argument("--pack", required=True)
    imp.add_argument("--style", default="generic", choices=sorted(STYLES))
    imp.add_argument("--default-category", default="reply")
    args = parser.parse_args()
    if args.cmd == "scan":
        return scan()
    if args.cmd == "validate":
        return validate()
    if args.cmd == "list":
        return list_stickers()
    if args.cmd == "catalog":
        return write_catalog()
    if args.cmd == "import":
        return import_dir(args.source, args.pack, args.style, args.default_category)
    return 1


if __name__ == "__main__":
    sys.exit(main())
