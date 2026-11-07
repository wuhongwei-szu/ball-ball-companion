#!/usr/bin/env python3
"""Send one AMR voice message directly through iLink (voice_item type 3).

This is an experimental path: iLink's voice rendering is known to be unreliable
(upstream issue #763). It does not depend on cc-connect TTS or ffmpeg at send
time; convert the audio to AMR beforehand.

Usage:
    python -X utf8 send_voice.py master path/to/voice.amr
    python -X utf8 send_voice.py xi path/to/voice.amr
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

MAX_AUDIO_BYTES = 5 * 1024 * 1024


class VoiceError(Exception):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage
        self.message = message


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _headers(token):
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": "Bearer " + token,
        "X-WECHAT-UIN": base64.b64encode(
            str(random.randint(0, 2**32 - 1)).encode()
        ).decode(),
    }


def _target(target):
    if target == "master":
        return c.MASTER_BOT_TOKEN, c.MASTER_SESSION, c.MASTER_CONTEXT_TOKENS
    if target == "xi":
        return c.XI_BOT_TOKEN, c.XI_SESSION, c.XI_CONTEXT_TOKENS
    raise VoiceError("config", "目标必须是 master 或 xi")


def _peer_context(token, session, context_path):
    if not token:
        raise VoiceError("config", "缺少该 bot 的 token")
    peer = c.session_peer(session)
    if not peer:
        raise VoiceError("config", "缺少 session")
    context_token = c.read_context_token(context_path, peer)
    if not context_token:
        raise VoiceError("context", "对方还没有给 bot 发过消息，无法主动发起")
    return peer, context_token


def _post_json(url, body, token, stage):
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=_headers(token),
    )
    try:
        with _opener().open(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise VoiceError(stage, f"HTTP {exc.code}: {detail}")
    except Exception as exc:
        raise VoiceError(stage, f"{type(exc).__name__}: {str(exc)[:200]}")


def _parse(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return {}


def send_voice(target, audio_path):
    c.assert_target(target)
    token, session, context_path = _target(target)
    peer, context_token = _peer_context(token, session, context_path)
    if not os.path.isfile(audio_path):
        raise VoiceError("audio", f"音频不存在：{audio_path}")
    raw = open(audio_path, "rb").read()
    if not raw:
        raise VoiceError("audio", "音频为空")
    if len(raw) > MAX_AUDIO_BYTES:
        raise VoiceError("audio", "音频超过 5MB")

    key = os.urandom(16)
    filekey = os.urandom(16).hex()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    upload_request = {
        "filekey": filekey,
        "media_type": 3,  # file/voice upload
        "to_user_id": peer,
        "rawsize": len(raw),
        "rawfilemd5": hashlib.md5(raw).hexdigest(),
        "filesize": len(ciphertext),
        "no_need_thumb": True,
        "aeskey": key.hex(),
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    _, _, raw_resp = _post_json(
        c.WEIXIN_API_BASE + "/ilink/bot/getuploadurl", upload_request, token, "getuploadurl"
    )
    upload = _parse(raw_resp)
    upload_url = upload.get("upload_full_url") or ""
    if not upload_url:
        upload_param = upload.get("upload_param", "")
        if not upload_param:
            raise VoiceError("getuploadurl", "响应缺少 upload_full_url/upload_param")
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
                raise VoiceError("cdn", "CDN 上传成功但缺少 x-encrypted-param")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            if 500 <= exc.code < 600 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise VoiceError("cdn", f"CDN 上传失败：HTTP {exc.code}: {body}")
        except VoiceError:
            raise
        except Exception as exc:
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise VoiceError("cdn", f"CDN 上传失败：{type(exc).__name__}: {str(exc)[:200]}")

    voice_item = {
        "media": {
            "encrypt_query_param": download_param,
            "aes_key": base64.b64encode(key.hex().encode()).decode(),
            "encrypt_type": 1,
        },
        "encode_type": 0,  # 0 = AMR
    }
    voice_text = os.environ.get("VOICE_TEXT", "").strip()
    if voice_text:
        voice_item["text"] = voice_text
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": peer,
            "client_id": "cc-" + os.urandom(8).hex(),
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 3, "voice_item": voice_item}],
            "context_token": context_token,
        },
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    _, _, raw_resp = _post_json(c.WEIXIN_API_URL, body, token, "sendmessage")
    result = _parse(raw_resp)
    if not result:
        return {"ok": True}
    ret = result.get("ret", -1)
    if ret == 0:
        return {"ok": True}
    errmsg = result.get("errmsg", "")
    if ret == -2:
        raise VoiceError("sendmessage", "上游 ret=-2（节流/会话异常），不要重试")
    raise VoiceError("sendmessage", f"ret={ret} errmsg={errmsg}")


def main():
    if len(sys.argv) < 3:
        print("用法: python -X utf8 send_voice.py master|xi <path.amr>")
        return 1
    try:
        send_voice(sys.argv[1], sys.argv[2])
    except VoiceError as exc:
        print(f"语音发送失败[{exc.stage}]：{exc.message}")
        return 1
    print("语音已发送（原生语音条是否显示取决于微信 iLink）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
