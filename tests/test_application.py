from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.application import Application
from src.config_manager import (
    AppConfig, GmailConfig, WordPressConfig, PathsConfig, RetryConfig,
)
from src.models import MailData


@pytest.fixture
def app_config(temp_project_dir: Path) -> AppConfig:
    template = temp_project_dir / "config" / "template.html"
    template.write_text("<!-- 前回の話 -->\n<!-- 以下本文 -->", encoding="utf-8")
    return AppConfig(
        gmail=GmailConfig(
            target_address="test@example.com",
            credentials_path=str(temp_project_dir / "config" / "credentials.json"),
            token_path=str(temp_project_dir / "config" / "token.json"),
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        ),
        wordpress=WordPressConfig(
            url="https://example.com",
            username="wp_user",
            application_password="dummy",
            default_status="draft",
            default_category="Blog",
        ),
        paths=PathsConfig(
            template=str(temp_project_dir / "config" / "template.html"),
            temp_dir=str(temp_project_dir / "temp"),
            image_dir=str(temp_project_dir / "images"),
            log_file=str(temp_project_dir / "logs" / "app.log"),
            history_file=str(temp_project_dir / "history" / "post_history.json"),
        ),
        retry=RetryConfig(max_count=1, initial_wait_seconds=0, backoff="exponential"),
        log_level="INFO",
    )


def _make_mail(tmp_path: Path, message_id: str = "msg-001") -> MailData:
    img = tmp_path / "IMG0001.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    return MailData(
        message_id=message_id,
        subject="テスト No1",
        title="テスト",
        number=1,
        category="Blog",
        scheduled_at=None,
        body="カテゴリー：Blog",
        attachment_paths=[img],
    )


def test_application_main_flow_mocked(app_config: AppConfig, tmp_path: Path) -> None:
    """正常系: Gmail取得→WP投稿→履歴保存まで一連のフローを検証する。"""
    mail = _make_mail(tmp_path)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        mock_wp.upload_media.return_value = (10, "https://example.com/img.jpg")
        mock_wp.get_or_create_category.return_value = 3
        mock_wp.find_latest_post_number.return_value = None
        mock_wp.create_post.return_value = (100, "https://example.com/?p=100")

        mock_wp.find_post_by_title.return_value = (None, None)

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_gmail.connect.assert_called_once()
        mock_gmail.fetch_unread.assert_called_once()
        mock_wp.upload_media.assert_called_once()
        mock_wp.create_post.assert_called_once()
        mock_history.find_by_message_id.assert_called_once_with("msg-001")
        mock_history.save.assert_called_once()


def test_application_skips_on_wp_failure(app_config: AppConfig, tmp_path: Path) -> None:
    """異常系: WP投稿失敗時は履歴を保存せず次のメールへ継続する。"""
    mail = _make_mail(tmp_path)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        mock_wp.upload_media.side_effect = Exception("API Error")

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_history.save.assert_not_called()


def test_application_skips_duplicate_mail(app_config: AppConfig, tmp_path: Path) -> None:
    """重複防止: 履歴に既存のmessage_idが見つかった場合は投稿処理をスキップする。"""
    mail = _make_mail(tmp_path)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = MagicMock()

        app.run()

        MockWp.return_value.create_post.assert_not_called()
        mock_history.save.assert_not_called()


def test_application_no_mails(app_config: AppConfig) -> None:
    """メールがない場合は何も投稿しない。"""
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp:

        MockGmail.return_value.fetch_unread.return_value = []
        app.run()
        MockWp.return_value.create_post.assert_not_called()
