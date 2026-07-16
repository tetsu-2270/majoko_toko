from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.header import Header
from email.message import EmailMessage
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config_manager import GmailConfig
from src.gmail_client import GmailClient, parse_body, parse_subject


class TestParseSubject:
    def test_half_width_space_and_bare_number(self):
        title, number = parse_subject("お菓子外しさんとカタカナ男 42")
        assert title == "お菓子外しさんとカタカナ男"
        assert number == 42

    def test_full_width_space_and_full_width_number(self):
        title, number = parse_subject("お菓子外しさんとカタカナ男　４２")
        assert title == "お菓子外しさんとカタカナ男"
        assert number == 42

    def test_half_width_tilde_format(self):
        title, number = parse_subject("お菓子外しさんとカタカナ男 ~ 42")
        assert title == "お菓子外しさんとカタカナ男"
        assert number == 42

    def test_full_width_wave_dash_and_full_width_space_format(self):
        title, number = parse_subject("お菓子外しさんとカタカナ男　〜　４２")
        assert title == "お菓子外しさんとカタカナ男"
        assert number == 42

    def test_preserves_japanese_title_untouched(self):
        title, number = parse_subject("魔女っこ日記 ~ 5")
        assert title == "魔女っこ日記"
        assert number == 5

    def test_number_in_middle_of_title_is_not_treated_as_episode(self):
        title, number = parse_subject("第2部の物語 ~ 41")
        assert title == "第2部の物語"
        assert number == 41

    def test_no_number_returns_whole_subject_as_title(self):
        """話数が無い件名は、件名全体を作品名として扱い話数はNoneを返す（呼び出し側で自動採番する）。"""
        title, number = parse_subject("お菓子外しさんとカタカナ男")
        assert title == "お菓子外しさんとカタカナ男"
        assert number is None

    def test_rejects_empty_subject(self):
        with pytest.raises(ValueError):
            parse_subject("")

    def test_rejects_trailing_separator_only(self):
        with pytest.raises(ValueError):
            parse_subject("お菓子外しさんとカタカナ男 ~")

    @pytest.mark.parametrize(
        "subject",
        [
            "AAAA No42",
            "AAAA No 42",
            "AAAA no42",
            "AAAA Ｎｏ４２",
            "AAAA Ｎｏ ４２",
        ],
    )
    def test_legacy_no_format_is_recognized_as_explicit_number(self, subject: str) -> None:
        """旧No形式（半角/全角、大文字/小文字、スペース有無）は、作品名"AAAA"・話数42として解析する。

        "AAAA No 42"のように"No"の後に空白がある場合でも、"No"を作品名へ取り込んで
        区切りなしの裸の数字と誤認しないこと（"AAAA No"を作品名にしない）を確認する。
        """
        title, number = parse_subject(subject)
        assert title == "AAAA"
        assert number == 42

    def test_rejects_no_marker_without_number(self) -> None:
        """"AAAA No"のようにNo表記だけが残り話数が存在しない件名は無効とする。"""
        with pytest.raises(ValueError):
            parse_subject("AAAA No")


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
        raw = _encode_raw(_make_email("魔女っこ日記 ~ 5", "カテゴリー：4コマ\n投稿日：2026/07/10 20:00"))

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
        assert mails[0].subject == "魔女っこ日記 ~ 5"
        assert mails[0].title == "魔女っこ日記"
        assert mails[0].number == 5
        assert mails[0].category == "4コマ"
        assert mails[0].scheduled_at == "2026/07/10 20:00"
        assert mails[0].message_id == "<abc@mail.gmail.com>"

    def test_parses_legacy_no_format_subject_as_explicit_number(self, gmail_config: GmailConfig) -> None:
        """"AAAA No42"のような旧No形式の件名も、実際のメール取得経路で作品名"AAAA"・話数42として解析される。"""
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email("AAAA No42", "カテゴリー：4コマ"))

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
        assert mails[0].title == "AAAA"
        assert mails[0].number == 42

    def test_subject_is_decoded_and_stripped_only(self, gmail_config: GmailConfig) -> None:
        """MailData.subjectはMIMEデコード後、前後の空白のみを除去した文字列である。"""
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email("  お菓子外しさんとカタカナ男 ~ 42  ", "カテゴリー：4コマ"))

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
        assert mails[0].subject == "お菓子外しさんとカタカナ男 ~ 42"

    def test_subject_without_number_has_none_number(self, gmail_config: GmailConfig) -> None:
        """話数が無い件名は、投稿対象としてMailData.number=Noneのまま取得される（自動採番はApplication側）。"""
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email("お菓子外しさんとカタカナ男", "カテゴリー：4コマ"))

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
        assert mails[0].title == "お菓子外しさんとカタカナ男"
        assert mails[0].number is None

    def test_skips_message_without_category(self, gmail_config: GmailConfig) -> None:
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email("タイトルのみ ~ 1", "本文のみでカテゴリなし"))

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

    @pytest.mark.parametrize("invalid_subject", ["", "お菓子外しさんとカタカナ男 ~"])
    def test_skips_invalid_subject_format(self, gmail_config: GmailConfig, invalid_subject: str) -> None:
        """空の件名、または区切り文字のみで話数が存在しない件名は自動補正せずスキップする。"""
        client = GmailClient(gmail_config)
        raw = _encode_raw(_make_email(invalid_subject, "カテゴリー：4コマ"))

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


class TestReceivedAtMs:
    """Gmail受信時刻(internalDate)の解決を検証する。"""

    def _run(self, gmail_config: GmailConfig, execute_return_value: dict) -> list:
        client = GmailClient(gmail_config)
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-1"}]
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            execute_return_value
        )
        client._service = mock_service
        return client.fetch_unread()

    def test_uses_internal_date(self, gmail_config: GmailConfig) -> None:
        raw = _encode_raw(_make_email("お菓子外しさんとカタカナ男 ~ 1", "カテゴリー：Blog"))
        mails = self._run(gmail_config, {"raw": raw, "internalDate": "1700000000000"})

        assert mails[0].received_at_ms == 1700000000000

    def test_falls_back_to_date_header_when_internal_date_missing(self, gmail_config: GmailConfig) -> None:
        msg = _make_email("お菓子外しさんとカタカナ男 ~ 1", "カテゴリー：Blog")
        msg["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
        raw = _encode_raw(msg)

        mails = self._run(gmail_config, {"raw": raw})

        expected_ms = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        assert mails[0].received_at_ms == expected_ms

    def test_prefers_internal_date_over_date_header(self, gmail_config: GmailConfig) -> None:
        msg = _make_email("お菓子外しさんとカタカナ男 ~ 1", "カテゴリー：Blog")
        msg["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
        raw = _encode_raw(msg)

        mails = self._run(gmail_config, {"raw": raw, "internalDate": "1700000000000"})

        assert mails[0].received_at_ms == 1700000000000

    def test_none_when_internal_date_and_date_header_both_missing(self, gmail_config: GmailConfig) -> None:
        raw = _encode_raw(_make_email("お菓子外しさんとカタカナ男 ~ 1", "カテゴリー：Blog"))
        mails = self._run(gmail_config, {"raw": raw})

        assert len(mails) == 1
        assert mails[0].received_at_ms is None

    def test_malformed_internal_date_falls_back_without_crashing(self, gmail_config: GmailConfig) -> None:
        """internalDateが不正値でもアプリを停止させず、Dateヘッダーへフォールバックする。"""
        msg = _make_email("お菓子外しさんとカタカナ男 ~ 1", "カテゴリー：Blog")
        msg["Date"] = "Mon, 01 Jan 2024 00:00:00 +0000"
        raw = _encode_raw(msg)

        mails = self._run(gmail_config, {"raw": raw, "internalDate": "not-a-number"})

        expected_ms = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        assert len(mails) == 1
        assert mails[0].received_at_ms == expected_ms


def _make_mail_with_attachments(
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]],
    message_id: str = "<abc@mail.gmail.com>",
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg.attach(MIMEText(body, "plain"))
    for filename, content in attachments:
        img = MIMEImage(content, _subtype="jpeg")
        img.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(img)
    return msg


class TestFetchUnreadAttachments:
    def _run(self, gmail_config: GmailConfig, msg: MIMEMultipart) -> list:
        client = GmailClient(gmail_config)
        raw = _encode_raw(msg)

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-1"}]
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg-1",
            "raw": raw,
        }
        client._service = mock_service
        return client.fetch_unread()

    def test_extracts_body_and_attachment(self, gmail_config: GmailConfig) -> None:
        msg = _make_mail_with_attachments(
            "魔女っこ日記 ~ 5",
            "カテゴリー：4コマ",
            [("IMG0001.jpg", b"\xff\xd8\xff" + b"\x00" * 10)],
        )
        mails = self._run(gmail_config, msg)

        assert len(mails) == 1
        assert len(mails[0].attachments) == 1
        attachment = mails[0].attachments[0]
        assert attachment.filename == "IMG0001.jpg"
        assert attachment.content == b"\xff\xd8\xff" + b"\x00" * 10
        assert attachment.content_type == "image/jpeg"

    def test_preserves_attachment_order(self, gmail_config: GmailConfig) -> None:
        msg = _make_mail_with_attachments(
            "タイトル ~ 1",
            "カテゴリー：Blog",
            [
                ("IMG0001.jpg", b"a"),
                ("IMG0002.jpg", b"b"),
                ("IMG0003.jpg", b"c"),
            ],
        )
        mails = self._run(gmail_config, msg)

        filenames = [a.filename for a in mails[0].attachments]
        assert filenames == ["IMG0001.jpg", "IMG0002.jpg", "IMG0003.jpg"]

    def test_decodes_mime_encoded_japanese_filename(self, gmail_config: GmailConfig) -> None:
        encoded_name = str(Header("画像.jpg", "utf-8"))
        msg = _make_mail_with_attachments(
            "タイトル ~ 1",
            "カテゴリー：Blog",
            [(encoded_name, b"\xff\xd8\xff")],
        )
        mails = self._run(gmail_config, msg)

        assert mails[0].attachments[0].filename == "画像.jpg"

    def test_no_attachments_returns_empty_list(self, gmail_config: GmailConfig) -> None:
        msg = _make_mail_with_attachments("タイトル ~ 1", "カテゴリー：Blog", [])
        mails = self._run(gmail_config, msg)

        assert mails[0].attachments == []

    def test_falls_back_to_gmail_api_id_when_message_id_missing(self, gmail_config: GmailConfig) -> None:
        msg = _make_mail_with_attachments("タイトル ~ 1", "カテゴリー：Blog", [], message_id="")
        del msg["Message-ID"]
        mails = self._run(gmail_config, msg)

        assert mails[0].message_id == "msg-1"


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
