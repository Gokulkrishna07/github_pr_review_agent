import hashlib
import hmac

from agent.webhook_verify import verify_signature


def _make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestVerifySignature:
    SECRET = "my-webhook-secret"
    PAYLOAD = b'{"action": "opened"}'

    def test_valid_signature_passes(self):
        sig = _make_signature(self.PAYLOAD, self.SECRET)
        assert verify_signature(self.PAYLOAD, sig, self.SECRET) is True

    def test_wrong_secret_rejected(self):
        sig = _make_signature(self.PAYLOAD, "wrong-secret")
        assert verify_signature(self.PAYLOAD, sig, self.SECRET) is False

    def test_tampered_payload_rejected(self):
        sig = _make_signature(self.PAYLOAD, self.SECRET)
        tampered = b'{"action": "deleted"}'
        assert verify_signature(tampered, sig, self.SECRET) is False

    def test_missing_sha256_prefix_rejected(self):
        raw_hex_digest = hmac.new(self.SECRET.encode("utf-8"), self.PAYLOAD, hashlib.sha256).hexdigest()
        # Provide raw hex without the "sha256=" prefix
        assert verify_signature(self.PAYLOAD, raw_hex_digest, self.SECRET) is False

    def test_empty_signature_rejected(self):
        assert verify_signature(self.PAYLOAD, "", self.SECRET) is False

    def test_correct_prefix_but_wrong_digest_rejected(self):
        assert verify_signature(self.PAYLOAD, "sha256=deadbeef", self.SECRET) is False

    def test_empty_payload_with_valid_signature_passes(self):
        payload = b""
        sig = _make_signature(payload, self.SECRET)
        assert verify_signature(payload, sig, self.SECRET) is True

    def test_binary_payload_works_correctly(self):
        payload = bytes(range(256))
        sig = _make_signature(payload, self.SECRET)
        assert verify_signature(payload, sig, self.SECRET) is True

    def test_binary_payload_with_wrong_secret_rejected(self):
        payload = bytes(range(256))
        sig = _make_signature(payload, "other-secret")
        assert verify_signature(payload, sig, self.SECRET) is False

    def test_none_signature_rejected(self):
        assert verify_signature(self.PAYLOAD, None, self.SECRET) is False

    def test_none_payload_rejected(self):
        assert verify_signature(None, "sha256=abc", self.SECRET) is False

    def test_none_secret_rejected(self):
        assert verify_signature(self.PAYLOAD, "sha256=abc", None) is False
