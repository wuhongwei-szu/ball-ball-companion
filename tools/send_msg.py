#!/usr/bin/env python3
"""Send one WeChat message as the companion and log it to raw memory.

Usage:
    python -X utf8 send_msg.py master "message"
    python -X utf8 send_msg.py xi "message"

Use one call per chat bubble. End the agent turn with NO_REPLY.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c


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


def send_xi(text):
    c.require(c.XI_SESSION, "xi_session（从 session 文件推导）")
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "send_xi.py")
    result = subprocess.run(
        [sys.executable, "-X", "utf8", helper, text],
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
    if len(sys.argv) < 3:
        print('用法: python -X utf8 send_msg.py master|xi "消息"')
        return 1
    target = sys.argv[1].lower()
    text = " ".join(sys.argv[2:]).strip()
    if not text:
        print("消息为空")
        return 1
    if target == "master":
        return send_master(text)
    if target == "xi":
        return send_xi(text)
    print("目标必须是 master 或 xi")
    return 1


if __name__ == "__main__":
    sys.exit(main())
