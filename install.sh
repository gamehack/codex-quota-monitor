#!/usr/bin/env bash
# Install on the Ubuntu host, as root, under /opt/codex-quota-monitor.
set -euo pipefail
APP=/opt/codex-quota-monitor
CONF=/etc/codex-quota-monitor
ENV_FILE="$CONF/monitor.env"
if (( EUID != 0 )); then echo '请以 root 运行安装器' >&2; exit 1; fi
if [[ "$(readlink -f "$(dirname "$0")")" != "$APP" ]]; then
  echo "先将仓库 clone 到 $APP" >&2; exit 1
fi
if [[ -z "${CODEX_USER:-}" ]]; then echo '请设置现有 Codex 登录用户 CODEX_USER' >&2; exit 1; fi
id "$CODEX_USER" >/dev/null || { echo 'CODEX_USER 不存在' >&2; exit 1; }
if [[ "$CODEX_USER" == root ]]; then echo '请使用现有 Codex 普通用户，而非 root' >&2; exit 1; fi
GROUP="$(id -gn "$CODEX_USER")"
USER_HOME="$(getent passwd "$CODEX_USER" | cut -d: -f6)"
CODEX_HOME="${CODEX_HOME:-$USER_HOME/.codex}"
CODEX_BIN="${CODEX_BIN:-$(runuser -u "$CODEX_USER" -- bash -lc 'command -v codex' 2>/dev/null || true)}"
if [[ -z "$CODEX_BIN" || "$CODEX_BIN" != /* || ! -x "$CODEX_BIN" ]]; then
  echo '找不到现有 Codex CLI，请通过 CODEX_BIN 指定绝对路径；不会重新安装' >&2; exit 1
fi
if [[ ! -d "$CODEX_HOME" ]]; then echo "CODEX_HOME 不存在: $CODEX_HOME" >&2; exit 1; fi
if [[ ! -f "$ENV_FILE" && -z "${FEISHU_WEBHOOK:-}" ]]; then
  echo '请复用现有飞书群 Webhook：提供 FEISHU_WEBHOOK 或预先建立私有 monitor.env' >&2; exit 1
fi
if [[ -n "${FEISHU_WEBHOOK:-}" && "$FEISHU_WEBHOOK" != https://* ]]; then
  echo 'Webhook 必须为 HTTPS 地址' >&2; exit 1
fi
install -d -m 755 "$CONF"
install -d -o "$CODEX_USER" -g "$GROUP" -m 700 "$APP/.state"
chmod 755 "$APP/run.sh"
if [[ -n "${FEISHU_WEBHOOK:-}" ]]; then
  # Secrets must never enter Git, CLI arguments, or logs.
  umask 077
  TMP="$(mktemp "$CONF/.env.XXXXXXXX")"
  {
    printf 'export CODEX_BIN=%q\n' "$CODEX_BIN"
    printf 'export CODEX_HOME=%q\n' "$CODEX_HOME"
    printf 'export FEISHU_WEBHOOK=%q\n' "$FEISHU_WEBHOOK"
    if [[ -n "${FEISHU_SIGN_SECRET:-}" ]]; then printf 'export FEISHU_SIGN_SECRET=%q\n' "$FEISHU_SIGN_SECRET"; fi
  } > "$TMP"
  chown "$CODEX_USER:$GROUP" "$TMP"
  chmod 600 "$TMP"
  mv -f "$TMP" "$ENV_FILE"
else
  chown "$CODEX_USER:$GROUP" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  runuser -u "$CODEX_USER" -- bash -c 'set -e; source "$1"; test -n "${FEISHU_WEBHOOK:-}"' _ "$ENV_FILE" || {
    echo 'monitor.env 缺少 FEISHU_WEBHOOK' >&2; exit 1;
  }
fi
if ! command -v crontab >/dev/null 2>&1; then echo '未安装 cron；停止部署' >&2; exit 1; fi
CRON="0 * * * * $APP/run.sh >> $APP/.state/cron.log 2>&1"
TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT
(crontab -u "$CODEX_USER" -l 2>/dev/null || true) | grep -v -F "$APP/run.sh" > "$TMP_CRON" || true
printf '%s\n' "$CRON" >> "$TMP_CRON"
crontab -u "$CODEX_USER" "$TMP_CRON"
echo "部署完成：$APP；每小时整点以 $CODEX_USER 身份执行"
echo "只读测试：sudo -u $CODEX_USER -H $APP/run.sh --dry-run"
echo "日志：$APP/.state/cron.log"
