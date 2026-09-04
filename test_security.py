from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from security import InitDataError, normalize_ip, score_risk, verify_telegram_init_data


class SecurityTests(unittest.TestCase):
    token = "test-bot-token"

    def make_init_data(self, auth_date: int | None = None) -> str:
        fields = {
            "auth_date": str(auth_date or int(time.time())),
            "query_id": "test-query",
            "user": json.dumps({"id": 12345, "first_name": "Test"}, separators=(",", ":")),
        }
        data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        secret = hmac.new(b"WebAppData", self.token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
        return urlencode(fields)

    def test_valid_telegram_init_data(self) -> None:
        verified = verify_telegram_init_data(self.make_init_data(), self.token)
        self.assertEqual(verified.user_id, 12345)

    def test_tampered_telegram_init_data_is_rejected(self) -> None:
        tampered = self.make_init_data().replace("first_name%22%3A%22Test", "first_name%22%3A%22Evil")
        with self.assertRaises(InitDataError):
            verify_telegram_init_data(tampered, self.token)

    def test_expired_telegram_init_data_is_rejected(self) -> None:
        with self.assertRaises(InitDataError):
            verify_telegram_init_data(self.make_init_data(int(time.time()) - 901), self.token)

    def test_ip_normalization(self) -> None:
        self.assertEqual(normalize_ip(" 203.0.113.8 "), "203.0.113.8")
        self.assertEqual(normalize_ip("[2001:db8::1]"), "2001:db8::1")
        self.assertIsNone(normalize_ip("not-an-ip"))

    def test_shared_ip_alone_is_low_risk(self) -> None:
        score, level, _ = score_risk(
            same_device_accounts=0, same_fingerprint_accounts=0,
            same_ip_accounts=1, same_network_accounts=0, recent_user_attempts=0,
        )
        self.assertEqual((score, level), (0, "low"))

    def test_linked_device_and_fingerprint_are_high_risk(self) -> None:
        score, level, reasons = score_risk(
            same_device_accounts=1, same_fingerprint_accounts=1,
            same_ip_accounts=0, same_network_accounts=0, recent_user_attempts=0,
        )
        self.assertEqual(level, "high")
        self.assertGreaterEqual(score, 70)
        self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()
