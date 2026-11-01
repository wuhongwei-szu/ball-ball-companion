#!/usr/bin/env python3
"""Generate a short Xiaoxiao (Edge TTS) MP3 and send it as a WeChat file.

Native iLink voice bubbles are rejected (ret=-1), so voice is delivered as an
MP3 file. The default voice is zh-CN-XiaoxiaoNeural.

Usage:
    python -X utf8 send_tts.py master "主人，晚安，做个好梦～"
    python -X utf8 send_tts.py xi "小主人，球球在呢～" --proactive
"""
import argparse
import os
import random
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

try:
    import send_xi
except Exception:
    send_xi = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_TEXT = 200
VOICE_KEEP = 50


def _voice_dir():
    os.makedirs(c.VOICE_DIR, exist_ok=True)
    return c.VOICE_DIR


def _prune_voice():
    try:
        files = [
            os.path.join(c.VOICE_DIR, n)
            for n in os.listdir(c.VOICE_DIR)
            if n.startswith("tts_") and n.endswith(".mp3")
        ]
        files.sort(key=os.path.getmtime, reverse=True)
        for path in files[VOICE_KEEP:]:
            os.remove(path)
    except Exception:
        pass


def generate_mp3(text, voice):
    if not c.EDGE_TTS_PYTHON or not os.path.isfile(c.EDGE_TTS_PYTHON):
        raise RuntimeError("Edge TTS Python 不存在：请在 bot.config.json 配置 edge_tts_python")
    if len(text) > MAX_TEXT:
        raise RuntimeError(f"语音文本太长（{len(text)} 字），请控制在 {MAX_TEXT} 字以内")
    out = os.path.join(
        _voice_dir(),
        "tts_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(3).hex() + ".mp3",
    )
    env = os.environ.copy()
    proxy = c.CFG.get("proxy", "")
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
    cmd = [
        c.EDGE_TTS_PYTHON, "-m", "edge_tts",
        "--voice", voice,
        "--text", text,
        "--write-media", out,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=90, env=env,
    )
    if result.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) < 1000:
        detail = (result.stderr or result.stdout or "").strip()[-300:]
        raise RuntimeError(f"Edge TTS 生成失败：{detail}")
    _prune_voice()
    return out


def _send_master(path):
    result = c.run_cc(
        ["send", "-p", c.PROJECT, "--session", c.MASTER_SESSION, "--file", path],
        timeout=120,
    )
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        raise RuntimeError(error or output or "cc-connect 发送文件失败")
    return True


def _send_xi(path):
    if send_xi is None:
        raise RuntimeError("缺少 send_xi 模块")
    try:
        send_xi.send_file(path)
    except Exception as exc:
        raise RuntimeError(f"小主人语音文件发送失败：{getattr(exc, 'message', str(exc))}")
    return True


def send_voice(target, text, voice, proactive=False, dry_run=False):
    text = " ".join(text.split()).strip()
    if not text:
        raise RuntimeError("语音文本为空")
    path = os.path.join(c.VOICE_DIR, "dry-run.mp3") if dry_run else generate_mp3(text, voice)
    print(f"[voice] {voice} -> {text}")
    if dry_run:
        print(f"[voice] dry-run file={path}")
        return 0
    if proactive:
        remaining, reason = c.proactive_remaining(target)
        if remaining <= 0:
            print(f"[budget] {reason}；这次不发语音")
            return 3
    if target == "master":
        _send_master(path)
    elif target == "xi":
        _send_xi(path)
    else:
        raise RuntimeError("目标必须是 master 或 xi")
    c.record_outbound(target, proactive=proactive)
    sid = "s1" if target == "master" else "s2"
    c.append_raw(sid, f"[语音:{voice}] {text}")
    c.append_recent(f"[语音] {text[:80]}")
    print("语音文件已发送（微信显示为文件，不是原生语音气泡）")
    return 0


def main():
    parser = argparse.ArgumentParser(description="用晓晓音色生成并发送语音 MP3")
    parser.add_argument("target", choices=["master", "xi"])
    parser.add_argument("text", nargs="+")
    parser.add_argument("--voice", default=c.EDGE_TTS_VOICE)
    parser.add_argument("--proactive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        return send_voice(args.target, " ".join(args.text), args.voice, args.proactive, args.dry_run)
    except RuntimeError as exc:
        print(f"语音发送失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
