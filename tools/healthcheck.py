#!/usr/bin/env python3
"""Read-only health check for the companion bot."""
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c
import capture_runtime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG_FILE = os.path.join(c.DATA_DIR, "config.toml")
JOBS_FILE = os.path.join(c.DATA_DIR, "crons", "jobs.json")
LOG_DIR = os.path.join(c.DATA_DIR, "logs")
BACKUP_DIR = os.path.join(c.WORK_DIR, "backups")


def ps(command):
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        return (result.stdout or "").strip()
    except Exception as exc:
        return f"ERR {exc}"


def latest(paths):
    files = [p for p in paths if os.path.isfile(p)]
    return max(files, key=os.path.getmtime) if files else None


def report_capture_health(jobs):
    job = next((j for j in jobs if isinstance(j, dict) and j.get("id") == "capture01"), None)
    health = capture_runtime.capture_health(c.CAPTURE_STATE_FILE + ".v2", job)
    healthy = health["capture_status"] == "ok"
    print(f"[{'OK' if healthy else '!!'}] archive capture: {health['capture_status']}"
          + (f" reason={health['reason']}" if health["reason"] else ""))
    print(f"[{'WARN' if health['coverage_status'] != 'no_recorded_gaps' else 'OK'}] "
          f"archive coverage: {health['coverage_status']} "
          f"review_pending={health['review_pending']} "
          f"(active={health.get('review_pending_active')}, legacy={health.get('review_pending_legacy')}) "
          f"review_boundaries={health['review_boundaries']}")
    return healthy


def main():
    ok = True
    print(f"== {c.BOT_NAME} 健康检查 ==")

    count = ps("(Get-Process -Name cc-connect -ErrorAction SilentlyContinue | Measure-Object).Count")
    process_ok = count.isdigit() and int(count) >= 1
    print(f"[{'OK' if process_ok else '!!'}] cc-connect 进程: {count}")
    if not process_ok:
        ok = False

    print(f"[{'OK' if os.path.isfile(CONFIG_FILE) else '!!'}] cc-connect 配置: {CONFIG_FILE}")
    if not os.path.isfile(CONFIG_FILE):
        ok = False

    sessions = 0
    if c.SESSION_FILE and os.path.isfile(c.SESSION_FILE):
        try:
            with open(c.SESSION_FILE, encoding="utf-8") as f:
                sessions = len(json.load(f).get("sessions", {}))
        except Exception:
            sessions = -1
    print(f"[{'OK' if sessions > 0 else '!!'}] 会话: {sessions}")
    if sessions <= 0:
        ok = False

    jobs = []
    if os.path.isfile(JOBS_FILE):
        try:
            with open(JOBS_FILE, encoding="utf-8") as f:
                jobs = json.load(f)
        except Exception:
            jobs = []
    enabled = sum(1 for j in jobs if j.get("enabled"))
    print(f"[{'OK' if enabled > 0 else '!!'}] 定时任务: {enabled} 启用 / {len(jobs)} 总数")
    if enabled <= 0:
        ok = False
    required = c.CFG.get("required_crons") or []
    if isinstance(required, list) and required:
        active_ids = {j.get("id") for j in jobs if j.get("enabled")}
        missing = [jid for jid in required if jid not in active_ids]
        print(f"[{'OK' if not missing else '!!'}] 必需定时任务: {len(required) - len(missing)}/{len(required)}")
        if missing:
            print("    缺失: " + ", ".join(str(x) for x in missing))
            ok = False
    if not report_capture_health(jobs):
        ok = False

    for name in ("MEMORY.md", "STATE.md", "EVENTS.md", "WEEKLY.md", "IMPROVEMENTS.md", "CARE_LOG.md"):
        path = os.path.join(c.MEMORY_DIR, name)
        print(f"[{'OK' if os.path.isfile(path) else '!!'}] 记忆文件: {name}")
        if not os.path.isfile(path):
            ok = False

    manifest_path = os.path.join(c.STICKER_DIR, "manifest.json")
    sticker_count = 0
    if os.path.isfile(manifest_path):
        data = c.load_json(manifest_path, {}) or {}
        stickers = data.get("stickers", [])
        sticker_count = len(stickers) if isinstance(stickers, list) else 0
    print(f"[{'OK' if sticker_count > 0 else '!!'}] 表情库: {sticker_count} 张 ({c.STICKER_DIR})")
    if sticker_count <= 0:
        ok = False

    threads = os.path.join(c.MEMORY_DIR, "THREADS.md")
    print(f"[{'OK' if os.path.isfile(threads) else '--'}] 未完话题: THREADS.md")

    last = os.path.join(c.MEMORY_DIR, "last-consolidation.txt")
    if os.path.isfile(last):
        lines = [l.strip() for l in open(last, encoding="utf-8") if l.strip()]
        print(f"[OK] 最近整理: {lines[-1] if lines else '（空）'}")
    else:
        print("[!!] 最近整理: 缺失")
        ok = False

    backups = glob.glob(os.path.join(BACKUP_DIR, "cc-weixin-*.zip"))
    latest_backup = latest(backups)
    if latest_backup:
        age_hours = (time.time() - os.path.getmtime(latest_backup)) / 3600.0
        print(f"[OK] 最近备份: {os.path.basename(latest_backup)} ({age_hours:.1f} 小时前)")
        if age_hours > 48:
            print("[WARN] 最近备份超过 48 小时，检查 cc-connect-backup 计划任务")
    else:
        print("[!!] 最近备份: 缺失")
        ok = False

    # Optional Platform usage cache: only inspect when an Admin key is configured.
    admin_env = os.path.join(c.WORK_DIR, "config", "openai_admin.env")
    admin_configured = False
    if os.path.isfile(admin_env):
        try:
            with open(admin_env, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip().startswith("OPENAI_ADMIN_KEY=") and line.split("=", 1)[1].strip():
                        admin_configured = True
                        break
        except OSError:
            pass
    usage_cache = os.path.join(c.MEMORY_DIR, "platform_usage.json")
    if admin_configured:
        if not os.path.isfile(usage_cache):
            print("[WARN] Platform 用量缓存: 缺失")
        else:
            try:
                with open(usage_cache, encoding="utf-8") as f:
                    payload = json.load(f)
                error = str(payload.get("error") or "")
                stamp = str(payload.get("updated_at") or "")
                age_min = None
                if stamp:
                    try:
                        now = datetime.datetime.now()
                        dt = datetime.datetime.strptime(f"{now.year}-{stamp}", "%Y-%m-%d %H:%M")
                        if dt > now + datetime.timedelta(days=1):
                            dt = dt.replace(year=now.year - 1)
                        age_min = (now - dt).total_seconds() / 60.0
                    except ValueError:
                        pass
                if error:
                    print(f"[WARN] Platform 用量缓存: {error}")
                elif age_min is not None and age_min > 90:
                    print(f"[WARN] Platform 用量缓存: {age_min:.0f} 分钟未更新")
                else:
                    print("[OK] Platform 用量缓存: 已配置且新鲜")
            except Exception as exc:
                print(f"[WARN] Platform 用量缓存: 读取失败 {type(exc).__name__}")
    else:
        print("[--] Platform 额度: 未配置 Admin key（可选）")

    latest_log = latest(glob.glob(os.path.join(LOG_DIR, "*.log")))
    errors = []
    if latest_log:
        with open(latest_log, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "level=ERROR" in line:
                    errors.append(line.strip())
    print(f"[{'OK' if not errors else '!!'}] 最近日志错误: {len(errors)}")
    if errors:
        print("    " + errors[-1][:200])
        ok = False

    tasks = ps("Get-ScheduledTask -TaskName cc-connect-watchdog,cc-connect-backup -ErrorAction SilentlyContinue | ForEach-Object { $_.TaskName + '=' + $_.State }")
    print(f"[OK] 计划任务: {tasks.replace(os.linesep, '; ')}")

    pending = 0
    try:
        timer_result = c.run_cc(["timer", "list"], timeout=15)
        out = timer_result.stdout or ""
        match = re.search(r"Pending timers \((\d+)\)", out)
        pending = int(match.group(1)) if match else 0
    except Exception as exc:
        print(f"[!!] 待触发提醒: 查询失败 {exc}")
    print(f"[OK] 待触发提醒: {pending}")

    care = "未规划"
    if os.path.isfile(c.CARE_PLAN_FILE):
        try:
            with open(c.CARE_PLAN_FILE, encoding="utf-8") as f:
                plan = json.load(f)
            care = f"{plan.get('date')} n={plan.get('n')}"
        except Exception:
            care = "读取失败"
    print(f"[OK] 今日关怀计划: {care}")

    print("== 结论:", "正常" if ok else "需要检查", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
