#!/usr/bin/env python3
"""Hourly ChatGPT Codex quota check via local codex app-server (stdlib only)."""
import argparse
import base64
import hashlib
import hmac
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

THRESHOLD = float(os.getenv("CODEX_QUOTA_THRESHOLD", "20"))
TIMEOUT = float(os.getenv("CODEX_QUOTA_TIMEOUT", "25"))
TIMEZONE = ZoneInfo(os.getenv("CODEX_QUOTA_TZ", "Asia/Shanghai"))


def get_limits():
    codex = os.getenv("CODEX_BIN") or shutil.which("codex")
    if not codex:
        raise RuntimeError("找不到现有 Codex CLI，请配置 CODEX_BIN")
    process = subprocess.Popen(
        [codex, "app-server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
    )
    messages = queue.Queue()
    deadline = time.monotonic() + TIMEOUT

    def reader():
        try:
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            messages.put(None)

    threading.Thread(target=reader, daemon=True).start()

    def send(value):
        process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def request(req_id, method, params=None):
        item = {"id": req_id, "method": method}
        if params is not None:
            item["params"] = params
        send(item)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"RPC timeout: {method}")
            try:
                reply = messages.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f"RPC timeout: {method}") from None
            if reply is None:
                raise RuntimeError("Codex App Server 已退出")
            if not isinstance(reply, dict) or reply.get("id") != req_id:
                continue
            if "error" in reply:
                raise RuntimeError(f"RPC error: {method}")  # Never log untrusted error payload.
            result = reply.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"Invalid RPC response: {method}")
            return result

    try:
        request(0, "initialize", {"clientInfo": {
            "name": "codex_quota_monitor", "title": "Codex Quota Monitor", "version": "1.0.0"
        }})
        send({"method": "initialized"})
        account = request(1, "account/read", {"refreshToken": False}).get("account") or {}
        if account.get("type") != "chatgpt":
            raise RuntimeError("Codex 未通过 ChatGPT 登录；请核对运行用户及 CODEX_HOME")
        plan = account.get("planType")
        if plan and str(plan).lower() != "plus":
            raise RuntimeError("当前 ChatGPT 订阅不是 Plus")
        return request(2, "account/rateLimits/read")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass


def collect_windows(payload):
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        old = payload.get("rateLimits")
        buckets = {old.get("limitId") or "codex": old} if isinstance(old, dict) else {}
    result = []
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for kind in ("primary", "secondary"):
            window = bucket.get(kind)
            if not isinstance(window, dict):
                continue
            used = window.get("usedPercent")
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
                continue
            result.append({
                "bucket": str(bucket_id), "window": kind,
                "remaining": round(100 - float(used), 1),
                "minutes": window.get("windowDurationMins"),
                "resets": window.get("resetsAt"),
            })
    if not result:
        raise RuntimeError("额度接口未返回可用窗口，不能按正常额度处理")
    return result


def reset_time(timestamp):
    if not isinstance(timestamp, (int, float)):
        return "未知"
    return datetime.fromtimestamp(timestamp, tz=TIMEZONE).strftime("%m-%d %H:%M")


def notify_feishu(low):
    webhook = os.getenv("FEISHU_WEBHOOK")
    if not webhook or not webhook.startswith("https://"):
        raise RuntimeError("未配置有效的 FEISHU_WEBHOOK")
    lines = [f"[Codex额度预警] 剩余额度低于 {THRESHOLD:g}%", "账号：ChatGPT Plus"]
    for w in low:
        duration = f"{w['minutes']}分钟" if w["minutes"] is not None else w["window"]
        lines.append(
            f"• {w['bucket']} / {duration}：剩余 {w['remaining']:g}%；"
            f"重置 {reset_time(w['resets'])}（北京时间）"
        )
    payload = {"msg_type": "text", "content": {"text": "\n".join(lines)}}
    if os.getenv("FEISHU_SIGN_SECRET"):
        stamp = str(int(time.time()))
        material = f"{stamp}\n{os.environ['FEISHU_SIGN_SECRET']}".encode()
        sig = hmac.new(material, b"", hashlib.sha256).digest()
        payload.update({"timestamp": stamp, "sign": base64.b64encode(sig).decode()})
    req = urllib.request.Request(
        webhook, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        body = res.read(4096)
    reply = json.loads(body) if body else {}
    if not isinstance(reply, dict) or reply.get("code", reply.get("StatusCode", 0)) != 0:
        raise RuntimeError("飞书机器人返回业务错误")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="读取真实额度，但不发飞书消息")
    args = parser.parse_args()
    windows = collect_windows(get_limits())
    low = [w for w in windows if w["remaining"] < THRESHOLD]
    if low and not args.dry_run:
        notify_feishu(low)
        print(f"告警已发送：{len(low)} 个额度窗口不足 {THRESHOLD:g}%")
    else:
        print(f"{'预演' if args.dry_run else '正常'}：检查 {len(windows)} 个额度窗口，最低剩余 {min(w['remaining'] for w in windows):g}%，低额度窗口 {len(low)} 个")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"监控失败：{exc}", file=sys.stderr)
        sys.exit(1)
