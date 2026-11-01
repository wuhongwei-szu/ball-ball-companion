#!/usr/bin/env python3
"""Send text or an image to the secondary WeChat bot via the ilink API.

The bot token and openids are read at runtime from cc-connect's config and
session files; they are never stored in bot.config.json.

Usage:
    python -X utf8 send_xi.py "text"
    python -X utf8 send_xi.py --image path/to/sticker.png
"""
import base64
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_IMAGE_BYTES = 2 * 1024 * 1024


class ILinkError(Exception):
    def __init__(self, stage, message, ret=None, errmsg=""):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.ret = ret
        self.errmsg = errmsg

    def exit_code(self):
        return 2 if self.stage in {"context", "config"} else 1


def _opener():
    # iLink and the WeChat CDN should be reached directly, not through Clash.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _headers():
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": "Bearer " + c.XI_BOT_TOKEN,
        "X-WECHAT-UIN": base64.b64encode(
            str(random.randint(0, 2**32 - 1)).encode()
        ).decode(),
    }


def _peer_and_context():
    if not c.XI_BOT_TOKEN:
        raise ILinkError("config", "缺少第二个 weixin bot 的 token（cc-connect 配置）")
    if not c.XI_SESSION:
        raise ILinkError("config", "缺少 xi_session（session 文件）")
    if not c.XI_CONTEXT_TOKENS:
        raise ILinkError("config", "缺少 xi context token 路径")
    peer = c.session_peer(c.XI_SESSION)
    context_token = c.read_context_token(c.XI_CONTEXT_TOKENS, peer)
    if not context_token:
        raise ILinkError(
            "context",
            "对方还没有给 bot 发过消息，微信不允许主动发起。请让对方先发一条消息。",
        )
    return peer, context_token


def _post_json(url, body, stage):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers=_headers())
    try:
        with _opener().open(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ILinkError(stage, f"HTTP {exc.code}: {detail}")
    except Exception as exc:
        raise ILinkError(stage, f"{type(exc).__name__}: {str(exc)[:200]}")


def _parse_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return {}


def _send_items(peer, context_token, item_list, client_id=None):
    body = {
        "msg": {
            "to_user_id": peer,
            "client_id": client_id or ("cc-" + os.urandom(6).hex()),
            "message_type": 2,
            "message_state": 2,
            "item_list": item_list,
            "context_token": context_token,
        },
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    _, _, raw = _post_json(c.WEIXIN_API_URL, body, "sendmessage")
    result = _parse_json(raw)
    if not result:
        return {"ok": True, "ret": 0, "errmsg": ""}
    ret = result.get("ret", -1)
    if ret == 0:
        return {"ok": True, "ret": 0, "errmsg": result.get("errmsg", "")}
    errmsg = result.get("errmsg", "")
    if ret == -2:
        raise ILinkError(
            "sendmessage",
            "上游返回 ret=-2（可能是会话过期或发送节流）。不要重试；先让对方发消息或稍后再试。",
            ret=ret,
            errmsg=errmsg,
        )
    raise ILinkError("sendmessage", f"发送失败：ret={ret} errmsg={errmsg}", ret=ret, errmsg=errmsg)


def send_text(message):
    peer, context_token = _peer_and_context()
    return _send_items(peer, context_token, [{"type": 1, "text_item": {"text": message}}])


def _prepare_image(path):
    if not os.path.isfile(path):
        raise ILinkError("image", f"图片不存在：{path}")
    raw = open(path, "rb").read()
    if not raw:
        raise ILinkError("image", "图片为空")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ILinkError("image", f"图片超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB，请先压缩")
    key = os.urandom(16)
    filekey = os.urandom(16).hex()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return raw, key, filekey, ciphertext


def send_image(path):
    peer, context_token = _peer_and_context()
    raw, key, filekey, ciphertext = _prepare_image(path)
    upload_request = {
        "filekey": filekey,
        "media_type": 1,
        "to_user_id": peer,
        "rawsize": len(raw),
        "rawfilemd5": hashlib.md5(raw).hexdigest(),
        "filesize": len(ciphertext),
        "no_need_thumb": True,
        "aeskey": key.hex(),
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    _, _, raw_resp = _post_json(
        c.WEIXIN_API_BASE + "/ilink/bot/getuploadurl", upload_request, "getuploadurl"
    )
    upload = _parse_json(raw_resp)
    upload_url = upload.get("upload_full_url") or ""
    if not upload_url:
        upload_param = upload.get("upload_param", "")
        if not upload_param:
            raise ILinkError("getuploadurl", "响应缺少 upload_full_url/upload_param")
        upload_url = c.WEIXIN_CDN_BASE_URL + "/upload?" + urllib.parse.urlencode(
            {"encrypted_query_param": upload_param, "filekey": filekey}
        )

    # CDN upload: encrypted body, no auth headers; 5xx may be retried, 4xx is final.
    last_error = None
    for attempt in range(3):
        request = urllib.request.Request(
            upload_url,
            data=ciphertext,
            method="POST",
            headers={"Content-Type": "application/octet-stream", "User-Agent": "cc-connect-weixin/1.0"},
        )
        try:
            with _opener().open(request, timeout=60) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                response.read()
            download_param = headers.get("x-encrypted-param", "")
            if not download_param:
                raise ILinkError("cdn", "CDN 上传成功但缺少 x-encrypted-param")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            last_error = f"HTTP {exc.code}: {body}"
            if 500 <= exc.code < 600 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：{last_error}")
        except ILinkError:
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：{last_error}")
    else:
        raise ILinkError("cdn", f"CDN 上传失败：{last_error}")

    image_item = {
        "media": {
            "encrypt_query_param": download_param,
            "aes_key": base64.b64encode(key.hex().encode()).decode(),
            "encrypt_type": 1,
        },
        "mid_size": len(ciphertext),
    }
    return _send_items(
        peer,
        context_token,
        [{"type": 2, "image_item": image_item}],
        client_id="cc-" + os.urandom(8).hex(),
    )


def send_file(path):
    peer, context_token = _peer_and_context()
    raw, key, filekey, ciphertext = _prepare_image(path)
    upload_request = {
        "filekey": filekey,
        "media_type": 3,
        "to_user_id": peer,
        "rawsize": len(raw),
        "rawfilemd5": hashlib.md5(raw).hexdigest(),
        "filesize": len(ciphertext),
        "no_need_thumb": True,
        "aeskey": key.hex(),
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    _, _, raw_resp = _post_json(
        c.WEIXIN_API_BASE + "/ilink/bot/getuploadurl", upload_request, "getuploadurl"
    )
    upload = _parse_json(raw_resp)
    upload_url = upload.get("upload_full_url") or ""
    if not upload_url:
        upload_param = upload.get("upload_param", "")
        if not upload_param:
            raise ILinkError("getuploadurl", "响应缺少 upload_full_url/upload_param")
        upload_url = c.WEIXIN_CDN_BASE_URL + "/upload?" + urllib.parse.urlencode(
            {"encrypted_query_param": upload_param, "filekey": filekey}
        )

    download_param = ""
    for attempt in range(3):
        request = urllib.request.Request(
            upload_url,
            data=ciphertext,
            method="POST",
            headers={"Content-Type": "application/octet-stream", "User-Agent": "cc-connect-weixin/1.0"},
        )
        try:
            with _opener().open(request, timeout=60) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                response.read()
            download_param = headers.get("x-encrypted-param", "")
            if not download_param:
                raise ILinkError("cdn", "CDN 上传成功但缺少 x-encrypted-param")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            if 500 <= exc.code < 600 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：HTTP {exc.code}: {body}")
        except ILinkError:
            raise
        except Exception as exc:
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：{type(exc).__name__}: {str(exc)[:200]}")

    file_item = {
        "media": {
            "encrypt_query_param": download_param,
            "aes_key": base64.b64encode(key.hex().encode()).decode(),
            "encrypt_type": 1,
        },
        "file_name": os.path.basename(path),
        "len": str(len(raw)),
    }
    return _send_items(
        peer,
        context_token,
        [{"type": 4, "file_item": file_item}],
        client_id="cc-" + os.urandom(8).hex(),
    )


def main():
    args = sys.argv[1:]
    if args and args[0] == "--image":
        if len(args) < 2:
            print("用法: python -X utf8 send_xi.py --image <path>")
            return 1
        try:
            result = send_image(args[1])
        except ILinkError as exc:
            print(f"发送失败[{exc.stage}]：{exc.message}")
            return exc.exit_code()
        print("已发送" if result.get("ok") else "发送失败")
        return 0 if result.get("ok") else 1
    if args and args[0] == "--file":
        if len(args) < 2:
            print("用法: python -X utf8 send_xi.py --file <path>")
            return 1
        try:
            result = send_file(args[1])
        except ILinkError as exc:
            print(f"发送失败[{exc.stage}]：{exc.message}")
            return exc.exit_code()
        print("已发送" if result.get("ok") else "发送失败")
        return 0 if result.get("ok") else 1

    message = " ".join(args) if args else sys.stdin.read()
    message = message.strip()
    if not message:
        print("消息为空")
        return 1
    try:
        result = send_text(message)
    except ILinkError as exc:
        print(f"发送失败[{exc.stage}]：{exc.message}")
        return exc.exit_code()
    print("已发送" if result.get("ok") else "发送失败")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
