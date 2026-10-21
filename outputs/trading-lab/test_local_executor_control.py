import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
from pathlib import Path

from local_executor_control import CommandRejected, LocalExecutorControl
from local_executor_service import build_server


class LocalExecutorControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "executor.sqlite3"
        self.secret = "a-long-test-only-executor-secret-0123456789"
        self.control = LocalExecutorControl(self.path, self.secret)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *, action="kill", command_id="cmd-1", nonce="nonce-1",
                issued_at="1000", body_extra=None):
        body = {"command_id": command_id, "action": action}
        body.update(body_extra or {})
        return body, self.control.sign(issued_at, nonce, body)

    def test_service_starts_disarmed_and_reports_no_order_capability(self):
        status = self.control.status()
        self.assertTrue(status["kill_switch"])
        self.assertFalse(status["entries_permitted"])
        self.assertFalse(status["live_order_submission"])
        self.assertEqual(status["broker_adapter"], "not_installed")

    def test_valid_signed_kill_command_is_audited_and_disarmed(self):
        body, signature = self.command()
        result = self.control.apply_command(body, issued_at="1000", nonce="nonce-1",
                                            signature=signature, now=1000)
        self.assertTrue(result["ok"])
        self.assertTrue(result["kill_switch"])
        self.assertEqual(self.control.status()["last_audit_event"], "kill")

    def test_replay_and_duplicate_command_ids_are_rejected(self):
        body, signature = self.command()
        args = dict(issued_at="1000", nonce="nonce-1", signature=signature, now=1000)
        self.control.apply_command(body, **args)
        with self.assertRaisesRegex(CommandRejected, "already been used"):
            self.control.apply_command(body, **args)
        other = {"command_id": "cmd-2", "action": "disarm"}
        signature = self.control.sign("1000", "nonce-1", other)
        with self.assertRaisesRegex(CommandRejected, "already been used"):
            self.control.apply_command(other, issued_at="1000", nonce="nonce-1",
                                       signature=signature, now=1000)

    def test_invalid_signature_expired_command_and_arm_request_fail_closed(self):
        body, signature = self.command()
        with self.assertRaisesRegex(CommandRejected, "signature"):
            self.control.apply_command(body, issued_at="1000", nonce="n1",
                                       signature="0" * 64, now=1000)
        with self.assertRaisesRegex(CommandRejected, "expired"):
            self.control.apply_command(body, issued_at="900", nonce="n2",
                                       signature=self.control.sign("900", "n2", body), now=1000)
        arm = {"command_id": "arm-1", "action": "arm"}
        with self.assertRaisesRegex(CommandRejected, "only disarm and kill"):
            self.control.apply_command(arm, issued_at="1000", nonce="n3",
                                       signature=self.control.sign("1000", "n3", arm), now=1000)
        self.assertTrue(self.control.status()["kill_switch"])

    def test_restart_forces_disarmed_state_and_records_it(self):
        body = {"command_id": "cmd-1", "action": "disarm"}
        signature = self.control.sign("1000", "n1", body)
        self.control.apply_command(body, issued_at="1000", nonce="n1",
                                   signature=signature, now=1000)
        restarted = LocalExecutorControl(self.path, self.secret)
        status = restarted.status()
        self.assertTrue(status["kill_switch"])
        self.assertFalse(status["entries_permitted"])
        self.assertEqual(status["last_audit_event"], "startup_disarmed")

    def test_secret_must_be_at_least_32_bytes(self):
        with self.assertRaisesRegex(ValueError, "at least 32"):
            LocalExecutorControl(self.path, "too-short")

    def test_http_service_refuses_remote_binding_and_missing_secret(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            build_server("0.0.0.0", 0, environ={"TRADINGBO_EXECUTOR_TOKEN": self.secret})
        with self.assertRaisesRegex(ValueError, "at least 32"):
            build_server("127.0.0.1", 0, environ={})

    def test_http_service_exposes_health_but_no_order_endpoint(self):
        server = build_server("127.0.0.1", 0, environ={
            "TRADINGBO_EXECUTOR_TOKEN": self.secret,
            "TRADINGBO_EXECUTOR_DB": str(self.path),
        })
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base + "/healthz", timeout=2) as response:
                self.assertEqual(response.status, 200)
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/v1/orders", timeout=2)
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
