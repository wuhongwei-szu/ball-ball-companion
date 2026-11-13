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
from send_xi import (
    ILinkError as VoiceError, _NoRedirect, _api_error, _cdn_request, _close_failed_response,
    _read_api_response, _send_response, _success_message,
)

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_AUDIO_BYTES = 5 * 1024 * 1024


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


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
    status = None
    try:
        request = urllib.request.Request(
            url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST", headers=_headers(token),
        )
        with _opener().open(request, timeout=30) as response:
            status, headers = response.status, response.headers
            raw = _read_api_response(response)
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            raw = _read_api_response(exc)
        except Exception as read_error:
            raise _api_error(stage, status, reason=type(read_error).__name__) from None
        finally:
            _close_failed_response(exc)
        raise _api_error(stage, status, raw) from None
    except Exception as exc:
        raise _api_error(stage, status, reason=type(exc).__name__) from None
    if status != 200:
        raise _api_error(stage, status, raw)
    return status, headers, raw


def _parse(raw):
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8", "replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


@c.outbound_serialized
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
        request = _cdn_request(upload_url, ciphertext)
        try:
            with _opener().open(request, timeout=60) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                response.read()
            download_param = headers.get("x-encrypted-param", "")
            if not download_param:
                raise VoiceError("cdn", "CDN 上传成功但缺少 x-encrypted-param")
            break
        except urllib.error.HTTPError as exc:
            _close_failed_response(exc)
            if 500 <= exc.code < 600 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise VoiceError("cdn", f"CDN 上传失败：HTTP {exc.code}") from None
        except VoiceError:
            raise
        except Exception as exc:
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise VoiceError("cdn", f"CDN 上传失败：{type(exc).__name__}") from None

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
    status, _, raw_resp = _post_json(c.WEIXIN_API_URL, body, token, "sendmessage")
    result = _send_response(status, raw_resp)
    c.record_outbound(target)
    return result


def main():
    if len(sys.argv) < 3:
        print("用法: python -X utf8 send_voice.py master|xi <path.amr>")
        return 1
    try:
        result = send_voice(sys.argv[1], sys.argv[2])
    except VoiceError as exc:
        print(f"语音发送失败[{exc.stage}]：{exc.message}")
        return 1
    if isinstance(result, int):
        return result
    print(_success_message(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
