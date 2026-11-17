#!/usr/bin/env bash
set -euo pipefail
umask 077
source /etc/codex-quota-monitor/monitor.env
cd /opt/codex-quota-monitor
exec /usr/bin/flock -n /opt/codex-quota-monitor/.state/monitor.lock \
  /usr/bin/python3 /opt/codex-quota-monitor/codex_quota_monitor.py "$@"
