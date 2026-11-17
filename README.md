# Codex Quota Monitor

Minimal ChatGPT Plus Codex quota monitor, intended for an Ubuntu host with an **existing Codex CLI + ChatGPT login**.

- Runs once per hour with cron; reports only if **any rate-limit window has strictly less than 20% remaining**.
- Reads `account/read` and `account/rateLimits/read` through a short-lived `codex app-server` stdio child process.
- Sends a Feishu custom-bot text webhook, optionally using Feishu signature verification.
- Python standard library only; no OpenClaw, Hermes, database, API key or separate resident daemon.
- Does not restart or change the already running Codex App Server. Does not create model turns or redeem reset credits.

## Host deployment (`/opt/codex-quota-monitor`)

Clone the public repo on the **Silicon Valley host**, not inside a container:

```bash
sudo git clone https://github.com/gamehack/codex-quota-monitor.git /opt/codex-quota-monitor
```

Determine the Linux owner, existing `codex` binary path, and `CODEX_HOME` of the **current authenticated Codex process**. Do not reinstall or re-login Codex.

Provide the existing Feishu webhook securely as an environment variable to the installer, or pre-create `/etc/codex-quota-monitor/monitor.env` containing `export FEISHU_WEBHOOK=...` (mode `0600`). The bot secret must never be committed to GitHub or printed by a bridge.

Example (replace `ubuntu` and both paths with actual values):

```bash
cd /opt/codex-quota-monitor
sudo env CODEX_USER=ubuntu CODEX_BIN=/absolute/path/to/codex \
  CODEX_HOME=/home/ubuntu/.codex FEISHU_WEBHOOK="$FEISHU_WEBHOOK" \
  bash ./install.sh
```

If the bot has signature verification enabled, also set `FEISHU_SIGN_SECRET` at installation. If a private env file already exists with `FEISHU_WEBHOOK`, you can omit the webhook from the installer environment; the private env file is reused.

The installer creates `/opt/codex-quota-monitor/.state/`, an owner-readable-only `/etc/codex-quota-monitor/monitor.env`, and an idempotent cron entry in **that Codex user's crontab**:

```cron
0 * * * * /opt/codex-quota-monitor/run.sh >> /opt/codex-quota-monitor/.state/cron.log 2>&1
```

## Validation

```bash
sudo -u ubuntu -H /opt/codex-quota-monitor/run.sh --dry-run
sudo crontab -u ubuntu -l
sudo tail -n 30 /opt/codex-quota-monitor/.state/cron.log
python3 -m unittest discover -s tests -v
```

`--dry-run` still reads real quotas but **never posts to Feishu**. For normal runs, quota at exactly 20% remaining does not alert; at 19% remaining it does. The default sends a new notification once per hour while a quota is low.

## Environment

| Name | Default | Purpose |
| --- | --- | --- |
| `CODEX_BIN` | `codex` from PATH | Existing CLI executable |
| `CODEX_HOME` | Codex user's default profile | Existing OAuth-backed Codex data directory |
| `FEISHU_WEBHOOK` | none | Existing Feishu custom-bot HTTPS webhook |
| `FEISHU_SIGN_SECRET` | none | Existing Feishu bot signing secret, if enabled |
| `CODEX_QUOTA_THRESHOLD` | `20` | Alert threshold, remaining percent |
| `CODEX_QUOTA_TZ` | `Asia/Shanghai` | Time zone for reset times |
| `CODEX_QUOTA_TIMEOUT` | `25` | Overall RPC timeout in seconds |

## Security and failure behavior

Run cron as the same **non-root** Linux user as Codex. Keep webhook/signing secrets in `/etc/codex-quota-monitor/monitor.env` at mode `0600`. Never print or copy `auth.json` or OAuth tokens. Codex itself may refresh credentials automatically. RPC failures and missing usage windows fail closed with a nonzero process status; no falsely reassuring OK message.

Docs: [Codex App Server](https://learn.chatgpt.com/docs/app-server) · [Feishu custom bot](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN).
