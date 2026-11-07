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
import http.client
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
MAX_API_RESPONSE_BYTES = 64 * 1024


class ILinkError(Exception):
    def __init__(self, stage, message, ret=None, errmsg="", *, errcode=None,
                 http_status=None, outcome="not_sent", response_kind=None):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.ret = ret
        self.errmsg = errmsg
        self.errcode = errcode
        self.http_status = http_status
        self.outcome = outcome
        self.response_kind = response_kind

    def exit_code(self):
        return 2 if self.stage in {"context", "config"} else 1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirected POST is not an acknowledgment from the send endpoint.
        return None


def _opener(*, allow_redirects=True):
    # iLink and the WeChat CDN should be reached directly, not through Clash.
    handlers = [urllib.request.ProxyHandler({})]
    if not allow_redirects:
        handlers.append(_NoRedirect())
    return urllib.request.build_opener(*handlers)


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


def _response_fields(raw):
    """Only return allowlisted diagnostics; never retain a raw body or errmsg."""
    if len(raw) > MAX_API_RESPONSE_BYTES:
        return None, None, "oversized", False
    if not raw.strip():
        return None, None, "empty", False

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            # Go encoding/json matches these struct fields case-insensitively.
            if key.casefold() in {"ret", "errcode", "errmsg"}:
                key = key.casefold()
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-JSON constant")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                            parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        return None, None, "invalid_json", False
    if not isinstance(result, dict):
        return None, None, "non_object", False
    codes = []
    valid = True
    for key in ("ret", "errcode"):
        value = result.get(key)
        if key in result and (type(value) is not int or not -(2**63) <= value < 2**63):
            valid = False
            value = "[invalid]"
        codes.append(value)
    kind = "object" if valid else "invalid_codes"
    if valid and result.get("errmsg") is not None and not isinstance(result["errmsg"], str):
        kind = "invalid_errmsg"
    return *codes, kind, bool(result.get("errmsg"))


def _api_error(stage, status, raw=b"", *, reason=None):
    ret, errcode, kind, has_errmsg = _response_fields(raw)
    # Non-200/transport failures do not prove the POST was never processed.
    rejected = status == 200 and kind == "object" and any(
        code is not None and code != 0 for code in (ret, errcode)
    )
    outcome = "rejected" if rejected else "uncertain"
    fields = (f"http_status={status if status is not None else 'unknown'} "
              f"ret={ret if ret is not None else 'absent'} "
              f"errcode={errcode if errcode is not None else 'absent'} "
              f"response={kind} errmsg={'[omitted]' if has_errmsg else 'absent'} "
              f"outcome={outcome}")
    if reason:
        fields += " transport=" + reason
    message = ("上游返回错误（不代表未送达）。" if rejected else "发送结果未确认。") + fields + "；请勿自动重发。"
    return ILinkError(stage, message, ret=ret, errmsg="[omitted]" if has_errmsg else "",
                      errcode=errcode, http_status=status, outcome=outcome,
                      response_kind=kind)


def _read_api_response(response):
    raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    # read(size) can silently return a truncated but parseable HTTP body,
    # whereas unbounded HTTPResponse.read() raises IncompleteRead. Keep the
    # size limit without losing the Content-Length completeness check.
    length = response.headers.get("Content-Length")
    if length is not None:
        length = length.strip()
        if not length or not length.isascii() or not length.isdecimal():
            raise ValueError("invalid Content-Length")
        expected = int(length)
        if len(raw) < min(expected, MAX_API_RESPONSE_BYTES + 1):
            raise http.client.IncompleteRead(b"", expected - len(raw))
    return raw


def _close_failed_response(response):
    # Cleanup of an already failed response must not replace its sanitized
    # error, leak a URL/token, or change whether another attempt is made.
    try:
        response.close()
    except Exception:
        pass


def _post_json(url, body, stage):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    status = None
    try:
        request = urllib.request.Request(url, data=data, method="POST", headers=_headers())
        with _opener(allow_redirects=False).open(request, timeout=30) as response:
            status = response.status
            headers = response.headers
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
        # Exception text may contain request URLs, credentials or user data.
        raise _api_error(stage, status, reason=type(exc).__name__) from None
    if status != 200 or len(raw) > MAX_API_RESPONSE_BYTES:
        raise _api_error(stage, status, raw)
    return status, headers, raw


def _send_response(status, raw):
    ret, errcode, kind, _ = _response_fields(raw)
    if (status != 200 or kind not in {"empty", "object"}
            or any(code is not None and code != 0 for code in (ret, errcode))):
        raise _api_error("sendmessage", status, raw)
    # Match cc-connect v1.5.0: HTTP 200 empty body / omitted zero-valued codes
    # are successful API acknowledgments. Do not fabricate ret=0 for an absent
    # field, or claim that an API acknowledgment proves recipient delivery.
    return {"ok": True, "ret": ret, "errcode": errcode, "errmsg": "",
            "http_status": status, "outcome": "accepted", "response_kind": kind,
            "acceptance_basis": "explicit_zero" if ret == 0 or errcode == 0 else "http_200_compatibility"}


def _success_message(result):
    if result.get("transport") == "cc-connect":
        return "cc-connect 报告发送成功（未确认收件人送达）：basis=cc_exit_zero"
    ret, errcode = result.get("ret"), result.get("errcode")
    return ("上游已接受（未确认收件人送达）："
            f"http_status={result.get('http_status')} "
            f"ret={ret if ret is not None else 'absent'} "
            f"errcode={errcode if errcode is not None else 'absent'} "
            f"response={result.get('response_kind')} basis={result.get('acceptance_basis')}")


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
            "from_user_id": "",
            "to_user_id": peer,
            "client_id": client_id or ("cc-" + os.urandom(6).hex()),
            "message_type": 2,
            "message_state": 2,
            "item_list": item_list,
            "context_token": context_token,
        },
        "base_info": {"channel_version": "cc-connect-weixin/1.0"},
    }
    status, _, raw = _post_json(c.WEIXIN_API_URL, body, "sendmessage")
    return _send_response(status, raw)


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


def _cdn_request(upload_url, ciphertext):
    try:
        return urllib.request.Request(
            upload_url, data=ciphertext, method="POST",
            headers={"Content-Type": "application/octet-stream", "User-Agent": "cc-connect-weixin/1.0"},
        )
    except Exception as exc:
        # Request construction can echo an invalid URL containing upload tokens.
        raise ILinkError("cdn", "CDN 请求无法创建：" + type(exc).__name__,
                         outcome="not_sent") from None


def _send_image_direct(path):
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
        request = _cdn_request(upload_url, ciphertext)
        try:
            with _opener().open(request, timeout=60) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                response.read()
            download_param = headers.get("x-encrypted-param", "")
            if not download_param:
                raise ILinkError("cdn", "CDN 上传成功但缺少 x-encrypted-param")
            break
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            _close_failed_response(exc)
            if 500 <= exc.code < 600 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：{last_error}") from None
        except ILinkError:
            raise
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：{last_error}") from None
    else:
        raise ILinkError("cdn", f"CDN 上传失败：{last_error}") from None

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


def _send_file_direct(path):
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
        request = _cdn_request(upload_url, ciphertext)
        try:
            with _opener().open(request, timeout=60) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                response.read()
            download_param = headers.get("x-encrypted-param", "")
            if not download_param:
                raise ILinkError("cdn", "CDN 上传成功但缺少 x-encrypted-param")
            break
        except urllib.error.HTTPError as exc:
            _close_failed_response(exc)
            if 500 <= exc.code < 600 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：HTTP {exc.code}") from None
        except ILinkError:
            raise
        except Exception as exc:
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ILinkError("cdn", f"CDN 上传失败：{type(exc).__name__}") from None

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


def _send_media_via_cc(path, flag):
    """Dispatch once via the already-selected active xi session; never fall back."""
    if not getattr(c, "CC_BIN", ""):
        raise ILinkError("config", "缺少 cc_bin；未发送，未切换到其他通道。", outcome="not_sent")
    try:
        result = c.run_cc([
            "send", "-p", c.PROJECT, "--session", c.XI_SESSION, flag, path,
        ], timeout=120)
        code = result.returncode
    except (Exception, SystemExit) as exc:
        # A timeout/read failure may happen after cc-connect sent the message.
        # Never expose stdout/stderr, command arguments or exception text.
        raise ILinkError(
            "cc_send", "cc-connect 发送结果未确认：transport=" + type(exc).__name__
            + "；请勿自动重发或改用其他通道。", outcome="uncertain",
            response_kind="process_error",
        ) from None
    if type(code) is not int or code != 0:
        safe_code = str(code) if type(code) is int and -(2**63) <= code < 2**63 else "[invalid]"
        raise ILinkError(
            "cc_send", "cc-connect 发送结果未确认：exit_code=" + safe_code
            + "；请勿自动重发或改用其他通道。", outcome="uncertain",
            response_kind="process_exit",
        )
    return {"ok": True, "ret": None, "errcode": None, "errmsg": "",
            "http_status": None, "outcome": "accepted", "response_kind": "process_exit",
            "acceptance_basis": "cc_exit_zero", "transport": "cc-connect"}


def _send_media(path, flag, direct_send):
    # Select exactly one route BEFORE a send attempt. An unavailable context
    # indicator means standalone explicit-XI direct mode, as in the repo base.
    target_probe = getattr(c, "current_target", None)
    try:
        use_cc = target_probe is not None and target_probe() == "xi" and bool(c.XI_SESSION)
    except (Exception, SystemExit) as exc:
        raise ILinkError("config", "无法确定媒体发送通道：" + type(exc).__name__,
                         outcome="not_sent", response_kind="route_error") from None
    if use_cc:
        return _send_media_via_cc(path, flag)
    return direct_send(path)


def send_image(path):
    return _send_media(path, "--image", _send_image_direct)


def send_file(path):
    return _send_media(path, "--file", _send_file_direct)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--image":
        if len(args) < 2:
            print("用法: python -X utf8 send_xi.py --image <path>")
            return 1
        try:
            result = send_image(args[1])
        except ILinkError as exc:
            print(f"发送未完成[{exc.stage}]：{exc.message}")
            return exc.exit_code()
        print(_success_message(result) if result.get("ok") else "发送未完成")
        return 0 if result.get("ok") else 1
    if args and args[0] == "--file":
        if len(args) < 2:
            print("用法: python -X utf8 send_xi.py --file <path>")
            return 1
        try:
            result = send_file(args[1])
        except ILinkError as exc:
            print(f"发送未完成[{exc.stage}]：{exc.message}")
            return exc.exit_code()
        print(_success_message(result) if result.get("ok") else "发送未完成")
        return 0 if result.get("ok") else 1

    message = " ".join(args) if args else sys.stdin.read()
    message = message.strip()
    if not message:
        print("消息为空")
        return 1
    try:
        result = send_text(message)
    except ILinkError as exc:
        print(f"发送未完成[{exc.stage}]：{exc.message}")
        return exc.exit_code()
    print(_success_message(result) if result.get("ok") else "发送未完成")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
