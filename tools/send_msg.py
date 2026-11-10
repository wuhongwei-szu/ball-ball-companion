#!/usr/bin/env python3
"""Send one WeChat message as the companion and log it to raw memory.

Usage:
    python -X utf8 send_msg.py master "message"
    python -X utf8 send_msg.py xi "message"
    python -X utf8 send_msg.py xi --relay "message"   # explicit cross-bot relay

Use one call per chat bubble. End the agent turn with NO_REPLY.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
from text_input import read_json_text


def send_master(text):
    c.require(c.MASTER_SESSION, "master_session（从 session 文件推导）")
    result = c.run_cc([
        "send", "-p", c.PROJECT, "--session", c.MASTER_SESSION, "-m", text,
    ])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if "send budget exhausted" in detail.lower() or "budget" in detail.lower():
            print("微信主动发送额度暂时用完，球球先不发了；等额度恢复或重新登录后再试。")
            return 2
        print(f"发送失败：{detail[:200]}")
        return 1
    c.append_raw("s1", text)
    c.append_recent(text)
    print("已发送")
    return 0


def send_xi(text, relay=False, *, lossless=False):
    c.require(c.XI_SESSION, "xi_session（从 session 文件推导）")
    # Select one transport before sending. A nonzero/unknown cc-connect result
    # may follow a successful send, so never retry it through direct iLink.
    allow_cc = c.current_target() == "xi" or (
        relay and c.context_token_fresh(c.XI_CONTEXT_TOKENS, 30)
    )
    if allow_cc and c.XI_SESSION:
        try:
            first = c.run_cc([
                "send", "-p", c.PROJECT, "--session", c.XI_SESSION, "-m", text,
            ], timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            print("文字发送结果未确认（cc-connect 调用异常）；不会切换通道补发，请先核实送达，不要重试。")
            return 1
        first_out = (first.stdout or "").strip()
        if first.returncode == 0:
            c.append_raw("s2", text)
            c.append_recent(text)
            print(first_out or "已发送")
            return 0
        print("文字发送结果未确认（cc-connect 返回非零状态）；不会切换通道补发，请先核实送达，不要重试。")
        return 1
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "send_xi.py")
    command = [sys.executable, "-X", "utf8", helper]
    stdin = {}
    if lossless:
        command.append("--json-stdin")
        stdin["input"] = json.dumps(text, ensure_ascii=True)
    else:
        command.append(text)
    result = subprocess.run(
        command,
        **stdin,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        print(output or (result.stderr or "").strip()[:200])
        return result.returncode
    c.append_raw("s2", text)
    c.append_recent(text)
    print(output or "已发送")
    return 0


def main():
    args = sys.argv[1:]
    relay = "--relay" in args
    if relay:
        args.remove("--relay")
    lossless = "--json-stdin" in args
    if lossless:
        args.remove("--json-stdin")
    if (lossless and len(args) != 1) or (not lossless and len(args) < 2):
        print('用法: python -X utf8 send_msg.py master|xi [--relay] "消息"')
        return 1
    target = args[0].lower()
    try:
        text = read_json_text() if lossless else " ".join(args[1:]).strip()
    except ValueError as exc:
        print(f"Invalid text input: {exc}")
        return 1
    if not text:
        print("消息为空")
        return 1
    c.assert_target(target, relay=relay)
    if target == "master":
        return send_master(text)
    if target == "xi":
        return send_xi(text, relay=relay, lossless=lossless)
    print("目标必须是 master 或 xi")
    return 1


if __name__ == "__main__":
    sys.exit(main())
