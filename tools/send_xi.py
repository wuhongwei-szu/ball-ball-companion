#!/usr/bin/env python3
"""Send a message to the secondary WeChat bot directly via the ilink API.

The bot token and openids are read at runtime from cc-connect's config and
session files; they are never stored in bot.config.json.
"""
import base64
import json
import os
import random
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
    else:
        message = sys.stdin.read()
    message = message.strip()
    if not message:
        print("消息为空")
        return 1

    c.require(c.XI_BOT_TOKEN, "第二个 weixin bot 的 token（cc-connect 配置）")
    c.require(c.XI_SESSION, "xi_session（session 文件）")
    c.require(c.XI_CONTEXT_TOKENS, "xi context token 路径")

    peer = c.XI_SESSION.split("weixin:dm:", 1)[1] if "weixin:dm:" in c.XI_SESSION else c.XI_SESSION
    try:
        with open(c.XI_CONTEXT_TOKENS, encoding="utf-8") as f:
            context_token = json.load(f).get(peer, "")
    except FileNotFoundError:
        context_token = ""
    if not context_token:
        print("对方还没有给 bot 发过消息，微信不允许主动发起。请让对方先发一条消息。")
        return 2

    body = {
        "msg": {
            "to_user_id": peer,
            "client_id": "cc-" + os.urandom(6).hex(),
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": message}}],
            "context_token": context_token,
        },
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    request = urllib.request.Request(
        c.WEIXIN_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": "Bearer " + c.XI_BOT_TOKEN,
            "X-WECHAT-UIN": base64.b64encode(
                str(random.randint(0, 2**32 - 1)).encode()
            ).decode(),
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read().decode("utf-8", "replace")
    except Exception as exc:
        print(f"发送失败：{type(exc).__name__} {str(exc)[:200]}")
        return 1

    try:
        result = json.loads(raw)
    except Exception:
        print(f"发送失败：响应无法解析 {raw[:200]}")
        return 1

    ret = result.get("ret", -1)
    if ret == 0:
        print("已发送")
        return 0
    if ret == -2:
        print("对方的会话上下文已过期，需要对方先给 bot 发一条消息。")
        return 2
    print(f"发送失败：ret={ret} errmsg={result.get('errmsg', '')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
