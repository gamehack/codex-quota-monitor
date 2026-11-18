#!/usr/bin/env bash
# Run interactively on the Silicon Valley host as root. Input is hidden and never echoed.
set -euo pipefail
umask 077

APP=/opt/codex-quota-monitor
CONF=/etc/codex-quota-monitor
ENV_FILE="$CONF/monitor.env"
CODEX_USER=ubuntu
CODEX_GROUP="$(id -gn "$CODEX_USER")"
CODEX_BIN=/home/ubuntu/.npm-global/bin/codex
CODEX_HOME=/home/ubuntu/.codex

if (( EUID != 0 )); then
  echo "请在硅谷服务器执行：sudo bash $APP/setup_interactive.sh" >&2
  exit 1
fi
if [[ ! -x "$CODEX_BIN" || ! -d "$CODEX_HOME" ]]; then
  echo "未找到此前核实的 Codex CLI/CODEX_HOME；停止，不安装或重新登录 Codex。" >&2
  exit 1
fi

install -d -o "$CODEX_USER" -g "$CODEX_GROUP" -m 700 "$CONF"
read -r -s -p "请输入飞书群机器人 Webhook（输入不回显）: " FEISHU_WEBHOOK
printf '\n'
if [[ "$FEISHU_WEBHOOK" != https://open.feishu.cn/open-apis/bot/v2/hook/* ]]; then
  unset FEISHU_WEBHOOK
  echo "Webhook 格式不正确，未写入配置。" >&2
  exit 1
fi
read -r -s -p "如机器人启用了签名校验，请输入签名密钥；未启用则直接回车（输入不回显）: " FEISHU_SIGN_SECRET
printf '\n'

TMP="$(mktemp "$CONF/.monitor.env.XXXXXXXX")"
cleanup() {
  rm -f "$TMP"
  unset FEISHU_WEBHOOK FEISHU_SIGN_SECRET
}
trap cleanup EXIT
{
  printf 'export CODEX_BIN=%q\n' "$CODEX_BIN"
  printf 'export CODEX_HOME=%q\n' "$CODEX_HOME"
  printf 'export FEISHU_WEBHOOK=%q\n' "$FEISHU_WEBHOOK"
  if [[ -n "$FEISHU_SIGN_SECRET" ]]; then
    printf 'export FEISHU_SIGN_SECRET=%q\n' "$FEISHU_SIGN_SECRET"
  fi
} > "$TMP"
chown "$CODEX_USER:$CODEX_GROUP" "$TMP"
chmod 600 "$TMP"
mv -f "$TMP" "$ENV_FILE"
unset FEISHU_WEBHOOK FEISHU_SIGN_SECRET

env CODEX_USER="$CODEX_USER" CODEX_BIN="$CODEX_BIN" CODEX_HOME="$CODEX_HOME" \
  bash "$APP/install.sh"

echo "执行真实额度只读测试（不会发送额度告警）..."
runuser -u "$CODEX_USER" -- "$APP/run.sh" --dry-run

echo "发送一条明确标记为测试的飞书消息..."
runuser -u "$CODEX_USER" -- "$APP/run.sh" --test-feishu

echo "完成：Webhook 配置权限为 0600；cron 已注册；真实额度读取与飞书测试均通过。"
echo "检查 cron：crontab -u $CODEX_USER -l"
echo "检查日志：$APP/.state/cron.log"
