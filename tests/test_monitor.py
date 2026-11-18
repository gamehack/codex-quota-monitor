import base64
import hashlib
import hmac
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import codex_quota_monitor as monitor


class MonitorTest(unittest.TestCase):
    def test_legacy_window(self):
        rows = monitor.collect_windows({"rateLimits": {
            "limitId": "codex", "primary": {"usedPercent": 81, "windowDurationMins": 300}}})
        self.assertEqual(rows[0]["remaining"], 19)

    def test_multi_bucket_and_strict_threshold(self):
        rows = monitor.collect_windows({"rateLimitsByLimitId": {
            "codex": {"primary": {"usedPercent": 80}, "secondary": {"usedPercent": 95}},
            "codex_other": {"primary": {"usedPercent": 40}}
        }})
        self.assertEqual([r["remaining"] for r in rows], [20, 5, 60])
        self.assertEqual(len([r for r in rows if r["remaining"] < 20]), 1)

    def test_missing_windows_fail(self):
        with self.assertRaises(RuntimeError):
            monitor.collect_windows({"rateLimits": {"primary": None}})

    def test_invalid_values_fail(self):
        with self.assertRaises(RuntimeError):
            monitor.collect_windows({"rateLimits": {"primary": {"usedPercent": "81"}}})

    def test_feishu_signature_matches_official_algorithm(self):
        timestamp, secret = "1700000000", "unit-test-secret"
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        expected = base64.b64encode(
            hmac.new(string_to_sign, b"", hashlib.sha256).digest()
        ).decode("utf-8")
        self.assertEqual(monitor.feishu_signature(timestamp, secret), expected)

    def test_dry_run_never_sends(self):
        with patch.object(monitor, "get_limits", return_value={
            "rateLimits": {"primary": {"usedPercent": 95}}
        }), patch.object(monitor, "notify_feishu") as send:
            with patch.object(sys, "argv", ["monitor", "--dry-run"]):
                monitor.main()
            send.assert_not_called()

    def test_test_feishu_does_not_query_codex(self):
        with patch.object(monitor, "get_limits", side_effect=AssertionError("must not query")), \
             patch.object(monitor, "send_feishu_text") as send:
            with patch.object(sys, "argv", ["monitor", "--test-feishu"]):
                monitor.main()
            send.assert_called_once()
            self.assertIn("测试", send.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
