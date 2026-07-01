from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config_manager import GmailConfig
from src.gmail_client import GmailClient, parse_body, parse_subject


class TestParseSubject:
    def test_with_number(self):
        title, number = parse_subject("魔女っこ日記 No5")
        assert title == "魔女っこ日記"
        assert number == 5

    def test_with_number_space(self):
        title, number = parse_subject("お話 No12")
        assert title == "お話"
        assert number == 12

    def test_without_number(self):
        title, number = parse_subject("新しい話")
        assert title == "新しい話"
        assert number is None

    def test_strips_whitespace(self):
        title, number = parse_subject("  タイトル No3  ")
        assert title == "タイトル"
        assert number == 3


class TestParseBody:
    def test_category_and_date(self):
        body = "カテゴリー：4コマ\n投稿日：2026/07/10 20:00"
        category, scheduled_at = parse_body(body)
        assert category == "4コマ"
        assert scheduled_at == "2026/07/10 20:00"

    def test_category_only(self):
        body = "カテゴリー：Blog"
        category, scheduled_at = parse_body(body)
        assert category == "Blog"
        assert scheduled_at is None

    def test_category_colon_ascii(self):
        body = "カテゴリ：お菓子"
        category, _ = parse_body(body)
        assert category == "お菓子"

    def test_missing_category_raises(self):
        with pytest.raises(ValueError):
            parse_body("投稿日：2026/07/10 20:00")


def test_gmail_client_interface_exists():
    assert hasattr(GmailClient, "connect")
    assert hasattr(GmailClient, "fetch_unread")
    assert hasattr(GmailClient, "disconnect")
    # gmail.readonlyスコープでは既読化・ラベル付与ができないため撤去済み
    assert not hasattr(GmailClient, "mark_as_read")
    assert not hasattr(GmailClient, "add_label")


@pytest.fixture
def gmail_config(tmp_path: Path) -> GmailConfig:
    return GmailConfig(
        target_address="test@example.com",
        credentials_path=str(tmp_path / "credentials.json"),
        token_path=str(tmp_path / "token.json"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


def _encode_raw(msg: EmailMessage) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _make_email(subject: str, body: str, message_id: str = "<abc@mail.gmail.com>") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg


class TestFetchUnread:
    def test_parses_unread_messages(self, gmail_config: GmailConfig) -> None:
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email("魔女っこ日記 No5", "カテゴリー：4コマ\n投稿日：2026/07/10 20:00"))

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-1"}]
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "raw": raw
        }
        client._service = mock_service

        mails = client.fetch_unread()

        assert len(mails) == 1
        assert mails[0].title == "魔女っこ日記"
        assert mails[0].number == 5
        assert mails[0].category == "4コマ"
        assert mails[0].scheduled_at == "2026/07/10 20:00"
        assert mails[0].message_id == "<abc@mail.gmail.com>"

    def test_skips_message_without_category(self, gmail_config: GmailConfig) -> None:
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email("タイトルのみ", "本文のみでカテゴリなし"))

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-1"}]
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "raw": raw
        }
        client._service = mock_service

        mails = client.fetch_unread()

        assert mails == []

    def test_no_messages(self, gmail_config: GmailConfig) -> None:
        client = GmailClient(gmail_config)
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {}
        client._service = mock_service

        assert client.fetch_unread() == []

    def test_raises_if_not_connected(self, gmail_config: GmailConfig) -> None:
        client = GmailClient(gmail_config)
        with pytest.raises(RuntimeError):
            client.fetch_unread()


class TestConnect:
    def test_uses_existing_valid_token(self, gmail_config: GmailConfig) -> None:
        Path(gmail_config.token_path).write_text("{}", encoding="utf-8")

        mock_creds = MagicMock(valid=True)
        with patch("src.gmail_client.Credentials.from_authorized_user_file", return_value=mock_creds) as mock_from_file, \
             patch("src.gmail_client.InstalledAppFlow") as mock_flow, \
             patch("src.gmail_client.build") as mock_build:

            client = GmailClient(gmail_config)
            client.connect()

            mock_from_file.assert_called_once()
            mock_flow.from_client_secrets_file.assert_not_called()
            mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds, cache_discovery=False)

    def test_runs_oauth_flow_when_no_token(self, gmail_config: GmailConfig) -> None:
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "dummy"}'

        with patch("src.gmail_client.InstalledAppFlow") as mock_flow_cls, \
             patch("src.gmail_client.build") as mock_build:
            mock_flow = mock_flow_cls.from_client_secrets_file.return_value
            mock_flow.run_local_server.return_value = mock_creds

            client = GmailClient(gmail_config)
            client.connect()

            mock_flow_cls.from_client_secrets_file.assert_called_once_with(
                gmail_config.credentials_path, gmail_config.scopes
            )
            assert Path(gmail_config.token_path).read_text(encoding="utf-8") == '{"token": "dummy"}'
            mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds, cache_discovery=False)

    def test_disconnect_clears_service(self, gmail_config: GmailConfig) -> None:
        client = GmailClient(gmail_config)
        client._service = MagicMock()
        client.disconnect()
        assert client._service is None
