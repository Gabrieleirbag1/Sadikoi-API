"""Brevo email sending: request shape and error handling (requests.post is faked, no network)."""
import requests

import email_sender


class FakeResponse:
    def __init__(self, status_code=201, payload=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_send_email_posts_to_brevo(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(201, {"messageId": "<abc@smtp-relay.mailin.fr>"})

    monkeypatch.setattr(email_sender, "BREVO_API_KEY", "test-key")
    monkeypatch.setattr(email_sender.requests, "post", fake_post)

    assert email_sender.send_email("bob@example.com", "Subject", "Body") is True
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == email_sender.BREVO_SEND_URL
    assert call["headers"]["api-key"] == "test-key"
    assert call["timeout"] == email_sender.BREVO_TIMEOUT_SECONDS
    assert call["json"] == {
        "sender": {"name": email_sender.EMAIL_SENDER_NAME, "email": email_sender.EMAIL_SENDER_ADDRESS},
        "to": [{"email": "bob@example.com"}],
        "subject": "Subject",
        "textContent": "Body",
    }


def test_send_email_returns_false_on_brevo_error(monkeypatch):
    monkeypatch.setattr(email_sender, "BREVO_API_KEY", "test-key")
    monkeypatch.setattr(email_sender.requests, "post", lambda *a, **k: FakeResponse(401, text='{"code":"unauthorized"}'))

    assert email_sender.send_email("bob@example.com", "Subject", "Body") is False


def test_send_email_returns_false_on_network_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(email_sender, "BREVO_API_KEY", "test-key")
    monkeypatch.setattr(email_sender.requests, "post", fake_post)

    assert email_sender.send_email("bob@example.com", "Subject", "Body") is False


def test_send_email_skips_without_api_key(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("must not call Brevo without an API key")

    monkeypatch.setattr(email_sender, "BREVO_API_KEY", None)
    monkeypatch.setattr(email_sender.requests, "post", fail_post)

    assert email_sender.send_email("bob@example.com", "Subject", "Body") is False


def test_auth_code_email_is_localized(monkeypatch):
    sent = []
    monkeypatch.setattr(email_sender, "send_email", lambda **kwargs: sent.append(kwargs))

    user = type("User", (), {"username": "bob", "email": "bob@example.com"})()
    device = type("Device", (), {"device_name": "Firefox", "ip_address": "1.2.3.4"})()
    email_sender.send_auth_code_email(user, device, "123456", language="fr")

    assert sent[0]["destinataire"] == "bob@example.com"
    assert "123456" in sent[0]["email_content"]
    assert sent[0]["email_subject"] == "Code de vérification pour votre connexion"
