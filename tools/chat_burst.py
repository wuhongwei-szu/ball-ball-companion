#!/usr/bin/env python3
"""Send a short burst of chat bubbles, optionally followed by one sticker.

This is the single agent-facing send entry for casual replies. It provides:
- any number of bubbles the agent passes (a sticker counts as one message);
- natural random spacing, with total sleep capped at 5 seconds;
- at most one sticker per call by default, no daily quota or cooldown unless
  configured in bot.config.json (0 = unlimited). iLink may still throttle.

Usage:
    python -X utf8 chat_burst.py master --sticker happy "第一句" "第二句"
    python -X utf8 chat_burst.py xi --sticker affection --style cat "第一句"
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import send_msg
import send_sticker

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAX_TOTAL_SLEEP = 5.0
MAX_BURST_MESSAGES = 6


def _delays(count, min_delay, max_delay, first_delay):
    if min_delay > max_delay:
        min_delay, max_delay = max_delay, min_delay
    delays = []
    for index in range(count):
        if index == 0 and first_delay is not None:
            delays.append(max(0.0, first_delay))
        elif index == 0:
            delays.append(random.uniform(0.3, 0.9))
        else:
            delays.append(random.uniform(min_delay, max_delay))
    total = sum(delays)
    if total > MAX_TOTAL_SLEEP and total > 0:
        factor = MAX_TOTAL_SLEEP / total
        delays = [round(d * factor, 2) for d in delays]
    return delays


def _send_text(target, text):
    if target == "master":
        return send_msg.send_master(text)
    return send_msg.send_xi(text)


def main():
    parser = argparse.ArgumentParser(description="发短消息 + 可选 1 张表情")
    parser.add_argument("target", choices=["master", "xi"])
    parser.add_argument("messages", nargs="+", help="每条气泡一句话")
    parser.add_argument("--sticker", help="表情分类；脚本按概率决定发不发")
    parser.add_argument("--sticker-prefer", help="按标签/文字偏好筛选，如 贴贴,抱,合十,击掌")
    parser.add_argument("--style", choices=["cat", "pig", "anime", "seio", "generic", "text", "silly"])
    parser.add_argument("--proactive", action="store_true", help="标记为主动消息，受本地主动安全预算约束")
    parser.add_argument("--probability", type=float, default=0.5, help="发表情的概率（0-1，默认 0.5）")
    parser.add_argument("--min-delay", type=float, default=0.7)
    parser.add_argument("--max-delay", type=float, default=1.8)
    parser.add_argument("--first-delay", type=float, default=None)
    parser.add_argument("--force-sticker", action="store_true", help="测试用：跳过表情冷却")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    messages = [m.strip() for m in args.messages if m.strip()]
    if not messages:
        print("消息为空")
        return 1
    probability = min(1.0, max(0.0, args.probability))

    send_sticker_flag = bool(args.sticker) and random.random() < probability
    if args.sticker and not send_sticker_flag:
        print(f"[sticker] 概率未命中（p={probability:.2f}），这次只发文字")

    # Local burst cap: generous, but not an unbounded wall of bubbles.
    allowed = MAX_BURST_MESSAGES - (1 if send_sticker_flag else 0)
    if len(messages) > allowed:
        print(f"[chat] 每轮本地安全上限 {MAX_BURST_MESSAGES} 条（表情算一条），已截断文字")
        messages = messages[:max(0, allowed)]

    # Proactive messages are the ones iLink throttles most; keep a safety
    # margin below the observed 4-6/24h server limit.
    if args.proactive:
        remaining, reason = c.proactive_remaining(args.target)
        if remaining <= 0:
            print(f"[budget] {reason}；这次先不发")
            return 3
        planned = len(messages) + (1 if send_sticker_flag else 0)
        if planned > remaining:
            text_budget = remaining - (1 if send_sticker_flag else 0)
            if text_budget <= 0:
                messages = []
                send_sticker_flag = bool(args.sticker)
            else:
                messages = messages[:text_budget]
            print(f"[budget] 主动消息本地剩余 {remaining} 条，已压缩本次发送")
        if not messages and not send_sticker_flag:
            print("[budget] 本次没有可发内容")
            return 3

    delays = _delays(len(messages), args.min_delay, args.max_delay, args.first_delay)

    if args.dry_run:
        print(f"[chat] dry-run target={args.target} bubbles={len(messages)} delays={delays} sticker={args.sticker if send_sticker_flag else None}")
        for index, text in enumerate(messages, 1):
            print(f"  {index}. {text}")
        if send_sticker_flag:
            send_sticker.send_one(
                args.target,
                category=args.sticker,
                style=args.style,
                proactive=args.proactive,
                force=args.force_sticker,
                dry_run=True,
                prefer=args.sticker_prefer,
            )
        return 0

    for index, text in enumerate(messages, 1):
        delay = delays[index - 1]
        if delay > 0:
            time.sleep(delay)
        code = _send_text(args.target, text)
        if code != 0:
            print(f"[chat] 第 {index} 条文字发送失败，停止后续发送（已发送 {index - 1} 条）")
            return code
        c.record_outbound(args.target, proactive=args.proactive)

    if send_sticker_flag:
        code = send_sticker.send_one(
            args.target,
            category=args.sticker,
            style=args.style,
            proactive=args.proactive,
            force=args.force_sticker,
            skip_budget=bool(args.proactive),
            prefer=args.sticker_prefer,
        )
        if code not in (0, 3):
            print("[chat] 文字已送达，表情发送失败；不要重发文字")
            return code
        if code == 3:
            print("[chat] 文字已送达，表情按限额/冷却跳过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
