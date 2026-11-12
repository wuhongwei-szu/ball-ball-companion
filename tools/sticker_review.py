#!/usr/bin/env python3
"""Build a sticker catalog (PDF + preview image + CSV) for human review.

Usage:
    python -X utf8 sticker_review.py
    python -X utf8 sticker_review.py --outdir C:/cc-weixin/artifacts/sticker_review
"""
import argparse
import csv
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MANIFEST = os.path.join(c.STICKER_DIR, "manifest.json")
DEFAULT_OUT = os.path.join(c.WORK_DIR, "artifacts", "sticker_review")
COLS = 4
ROWS = 5
CELL_W = 340
CELL_H = 330
MARGIN = 30
HEADER = 110
FOOTER = 45


def _prefer_review_venv():
    """Use the dedicated review venv when present.

    The system Python on this machine can crash inside Pillow/reportlab while
    decoding some GIFs; the review venv has a stable dependency set. The public
    repository usually has no .venv-review, so it simply keeps the current
    interpreter.
    """
    if os.name != "nt" or ".venv-review" in sys.executable:
        return
    venv_py = os.path.join(c.WORK_DIR, ".venv-review", "Scripts", "python.exe")
    if os.path.isfile(venv_py) and os.path.abspath(venv_py) != os.path.abspath(sys.executable):
        os.execv(venv_py, [venv_py, os.path.abspath(__file__)] + sys.argv[1:])
FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

CATEGORY_ORDER = [
    "happy", "affection", "comfort", "meow", "shy", "teasing", "surprised",
    "confused", "sad", "angry", "sleep", "greeting",
    "food", "work", "entertainment", "like",
]


def _font(size, bold=False):
    for path in ((FONT_BOLD if bold else FONT_REGULAR), FONT_REGULAR):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _ellipsize(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _sort_key(entry):
    try:
        rank = CATEGORY_ORDER.index(entry["category"])
    except ValueError:
        rank = len(CATEGORY_ORDER)
    return (rank, entry.get("style", ""), entry.get("label", ""), entry.get("id", ""))


def _load_thumb(path, size):
    try:
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            im = im.convert("RGB")
            im.thumbnail((size, size))
            tile = Image.new("RGB", (size, size), "white")
            tile.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
            return tile
    except Exception:
        return Image.new("RGB", (size, size), "#eeeeee")


def build(outdir):
    manifest = c.load_json(MANIFEST, None)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("stickers"), list):
        raise SystemExit("manifest 不存在，请先运行 sticker_admin.py scan")
    entries = sorted(manifest["stickers"], key=_sort_key)
    os.makedirs(outdir, exist_ok=True)
    pages_dir = os.path.join(outdir, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    per_page = COLS * ROWS
    page_w = MARGIN * 2 + COLS * CELL_W
    page_h = HEADER + ROWS * CELL_H + FOOTER + MARGIN
    pages = []
    csv_rows = []
    total_pages = (len(entries) + per_page - 1) // per_page

    for page_index in range(total_pages):
        page = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        title_font = _font(30, bold=True)
        sub_font = _font(17)
        label_font = _font(18, bold=True)
        meta_font = _font(15)
        idx_font = _font(16, bold=True)
        draw.text((MARGIN, 22), "球球表情图鉴", font=title_font, fill="#222222")
        draw.text(
            (MARGIN, 62),
            f"共 {len(entries)} 张 · 第 {page_index + 1}/{total_pages} 页 · "
            "编号在每格左上角；分类/风格/是否动图见格子下方",
            font=sub_font, fill="#666666",
        )
        draw.line((MARGIN, HEADER - 12, page_w - MARGIN, HEADER - 12), fill="#dddddd", width=1)

        chunk = entries[page_index * per_page:(page_index + 1) * per_page]
        for cell_index, entry in enumerate(chunk):
            row, col = divmod(cell_index, COLS)
            x = MARGIN + col * CELL_W
            y = HEADER + row * CELL_H
            number = page_index * per_page + cell_index + 1
            thumb_size = 250
            thumb = _load_thumb(os.path.join(c.STICKER_DIR, entry["file"]), thumb_size)
            page.paste(thumb, (x + (CELL_W - thumb_size) // 2, y + 6))
            draw.rectangle((x + 3, y + 3, x + CELL_W - 3, y + CELL_H - 3), outline="#e5e5e5", width=1)
            draw.text((x + 10, y + 8), f"#{number:03d}", font=idx_font, fill="#d9480f")
            label = _ellipsize(draw, entry.get("label", ""), label_font, CELL_W - 20)
            draw.text((x + 10, y + thumb_size + 14), label, font=label_font, fill="#222222")
            meta = f"{entry.get('category_label', entry['category'])} · {entry.get('style_label', entry['style'])}"
            if entry.get("animated"):
                meta += " · 动图"
            draw.text((x + 10, y + thumb_size + 42), _ellipsize(draw, meta, meta_font, CELL_W - 20),
                      font=meta_font, fill="#777777")
            csv_rows.append({
                "number": number, "id": entry["id"], "category": entry["category"],
                "category_label": entry.get("category_label", ""), "style": entry["style"],
                "style_label": entry.get("style_label", ""), "label": entry.get("label", ""),
                "animated": entry.get("animated", False), "tags": "|".join(entry.get("tags", [])),
                "file": entry["file"],
            })
        draw.text((page_w - MARGIN - 120, page_h - FOOTER + 8),
                  f"球球 · {page_index + 1}/{total_pages}", font=meta_font, fill="#999999")
        page_path = os.path.join(pages_dir, f"page_{page_index + 1:02d}.png")
        page.save(page_path)
        pages.append(page)

    pdf_path = os.path.join(outdir, "sticker_catalog.pdf")
    if pages:
        pages[0].save(pdf_path, save_all=True, append_images=pages[1:], resolution=100.0)
    preview_path = os.path.join(outdir, "preview_01.png")
    if pages:
        pages[0].save(preview_path)
    csv_path = os.path.join(outdir, "sticker_catalog.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else [])
        writer.writeheader()
        writer.writerows(csv_rows)

    # Simple local HTML gallery (relative paths; for desktop review).
    html_path = os.path.join(outdir, "index.html")
    cards = []
    for row in csv_rows:
        src = os.path.relpath(os.path.join(c.STICKER_DIR, row["file"]), outdir).replace("\\", "/")
        cards.append(
            f'<div class="card"><div class="num">#{row["number"]:03d}</div>'
            f'<img loading="lazy" src="{src}" alt="">'
            f'<div class="label">{row["label"]}</div>'
            f'<div class="meta">{row["category_label"]} · {row["style_label"]}'
            f'{" · 动图" if row["animated"] else ""}</div></div>'
        )
    html = (
        "<!doctype html><meta charset='utf-8'><title>球球表情图鉴</title>"
        "<style>body{font-family:'Microsoft YaHei',sans-serif;background:#fafafa;margin:24px}"
        "h1{font-size:24px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px}"
        ".card{background:white;border:1px solid #eee;border-radius:12px;padding:8px;position:relative}"
        ".card img{width:100%;height:160px;object-fit:contain;background:white}"
        ".num{position:absolute;top:10px;left:10px;color:#d9480f;font-weight:bold;font-size:13px}"
        ".label{font-weight:bold;font-size:14px;margin-top:4px}.meta{color:#888;font-size:12px}"
        "</style><h1>球球表情图鉴 · " + str(len(entries)) + " 张</h1><div class='grid'>"
        + "".join(cards) + "</div>"
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"CATALOG pages={total_pages} stickers={len(entries)}")
    print(f"  pdf={pdf_path}")
    print(f"  preview={preview_path}")
    print(f"  csv={csv_path}")
    print(f"  html={html_path}")
    return pdf_path, preview_path, csv_path


def main():
    _prefer_review_venv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
