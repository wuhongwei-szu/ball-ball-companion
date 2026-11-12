#!/usr/bin/env python3
"""Copy the latest inbound image/sticker into the local sticker library.

Usage:
    python -X utf8 learn_sticker.py --owner xi --latest --category affection
    python -X utf8 learn_sticker.py --owner master --path C:/.../img.jpg --category teasing
"""
import argparse
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import sticker_admin

IMAGE_EXTS = {".gif", ".png", ".jpg", ".jpeg", ".webp"}
INBOUND_DIR = os.path.join(c.WORK_DIR, ".cc-connect", "images")


def latest_inbound():
    if not os.path.isdir(INBOUND_DIR):
        raise SystemExit(f"入站图片目录不存在: {INBOUND_DIR}")
    files = [
        os.path.join(INBOUND_DIR, n) for n in os.listdir(INBOUND_DIR)
        if os.path.splitext(n)[1].lower() in IMAGE_EXTS
    ]
    if not files:
        raise SystemExit("没有找到入站图片")
    return max(files, key=os.path.getmtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, choices=["master", "xi"])
    parser.add_argument("--path")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--category", default="like")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    c.assert_target(args.owner)
    src = args.path or (latest_inbound() if args.latest else "")
    if not src or not os.path.isfile(src):
        raise SystemExit("请用 --path 指定图片，或 --latest 取最新入站图片")
    category = args.category if args.category in sticker_admin.CATEGORY_DESCRIPTIONS else "like"
    size = os.path.getsize(src)
    if size > sticker_admin.MAX_BYTES:
        raise SystemExit(f"图片超过 {sticker_admin.MAX_BYTES // 1024 // 1024}MB")
    info = sticker_admin._image_info(src)
    if info is None:
        raise SystemExit("图片无法读取")
    if min(info[0], info[1]) < sticker_admin.MIN_DIM:
        raise SystemExit(f"图片太小（{info[0]}x{info[1]}），至少 {sticker_admin.MIN_DIM}px")
    digest = hashlib.sha256(open(src, "rb").read()).hexdigest()
    pack = "learned-" + args.owner
    dest_dir = os.path.join(c.STICKER_DIR, pack, category)
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(src)[1].lower()
    dest = os.path.join(dest_dir, digest[:10] + ext)
    if not os.path.exists(dest):
        shutil.copy2(src, dest)
    sticker_admin.scan()
    print(f"LEARNED {pack}/{category}/{os.path.basename(dest)} label={args.label or '(auto)'}")


if __name__ == "__main__":
    sys.exit(main())
