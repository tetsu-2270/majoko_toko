from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.application import Application
from src.config_manager import (
    AppConfig, GmailConfig, WordPressConfig, PathsConfig, RetryConfig,
)
from src.models import AttachmentData, MailData


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


def _make_mail(
    message_id: str = "msg-001",
    filenames: list[str] | None = None,
    title: str = "テスト",
    number: int | None = 1,
    received_at_ms: int | None = None,
) -> MailData:
    if filenames is None:
        filenames = ["IMG0001.jpg"]
    attachments = [
        AttachmentData(filename=name, content=b"\xff\xd8\xff", content_type="image/jpeg")
        for name in filenames
    ]
    return MailData(
        message_id=message_id,
        subject=f"{title} ~ {number}" if number is not None else title,
        title=title,
        number=number,
        category="Blog",
        scheduled_at=None,
        body="カテゴリー：Blog",
        attachments=attachments,
        received_at_ms=received_at_ms,
    )


def _setup_wp_mock(mock_wp: MagicMock) -> None:
    mock_wp.upload_media.return_value = (10, "https://example.com/img.jpg")
    mock_wp.get_or_create_category.return_value = 3
    mock_wp.find_latest_post_number.return_value = None
    mock_wp.create_post.return_value = (100, "https://example.com/?p=100")
    mock_wp.find_post_by_title.return_value = (None, None)


class _FakeWordPressClient:
    """投稿成功記事を保持する状態付きWordPressClient代替（複数メール回帰テスト専用）。

    `existing_titles`で与えたタイトルのみを検索対象（WordPress上に既存の記事）として扱う。
    `create_post()`で新規作成した記事は、実運用でWordPressの検索インデックスが即座に
    反映されない場合があることを模すため、意図的に検索対象へ含めない
    （Application側の実行中キャッシュだけが同一実行内での参照手段になる）。
    """

    _NEW_FORMAT_RE = re.compile(r"^(.+?)\s*~\s*(\d+)\s*$")
    _LEGACY_FORMAT_RE = re.compile(r"^(.+?)\s+No\s*(\d+)\s*$", re.IGNORECASE)

    def __init__(self, existing_titles: list[str] | None = None) -> None:
        self._searchable_titles: list[str] = list(existing_titles or [])
        self._next_post_id = 1000
        self._next_media_id = 1
        self.created_posts: list[dict] = []
        self.upload_media_calls: list[Path] = []
        self.fail_titles: set[str] = set()

    def get_or_create_category(self, name: str) -> int:
        return 1

    def upload_media(self, image_path: Path) -> tuple[int, str]:
        self.upload_media_calls.append(image_path)
        media_id = self._next_media_id
        self._next_media_id += 1
        return media_id, f"https://example.com/media/{image_path.name}"

    def find_post_by_title(self, title: str) -> tuple[str | None, str | None]:
        for candidate in self._searchable_titles:
            if candidate == title:
                return f"https://example.com/?seed={candidate}", candidate
        return None, None

    def find_latest_post_number(self, title_prefix: str) -> int | None:
        numbers: list[int] = []
        for candidate in self._searchable_titles:
            m = self._NEW_FORMAT_RE.match(candidate) or self._LEGACY_FORMAT_RE.match(candidate)
            if m and m.group(1) == title_prefix:
                numbers.append(int(m.group(2)))
        return max(numbers) if numbers else None

    def create_post(
        self,
        title: str,
        content: str,
        category_id: int,
        featured_media_id: int | None = None,
        status: str | None = None,
        scheduled_at: str | None = None,
    ) -> tuple[int, str]:
        if title in self.fail_titles:
            raise RuntimeError(f"投稿失敗をシミュレート: {title}")
        post_id = self._next_post_id
        self._next_post_id += 1
        url = f"https://example.com/?p={post_id}"
        self.created_posts.append({
            "id": post_id, "title": title, "link": url, "content": content,
            "category_id": category_id, "featured_media_id": featured_media_id,
            "scheduled_at": scheduled_at,
        })
        return post_id, url


def test_application_main_flow_mocked(app_config: AppConfig) -> None:
    """正常系: Gmail取得(添付データ)→保存→WP投稿→履歴保存まで一連のフローを検証する。

    AttachmentManagerはモックせず実物を通すことで、GmailClient→MailData.attachments
    →AttachmentManager→ImageSorter→WordPressClientの接続漏れを検出できるようにする。
    """
    mail = _make_mail()
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_gmail.connect.assert_called_once()
        mock_gmail.fetch_unread.assert_called_once()
        mock_wp.upload_media.assert_called_once()
        mock_wp.create_post.assert_called_once()
        mock_history.find_by_message_id.assert_called_once_with("msg-001")
        mock_history.save.assert_called_once()

        saved_image = Path(app_config.paths.image_dir) / "IMG0001.jpg"
        assert saved_image.exists()


def test_application_creates_post_with_explicit_number_format(app_config: AppConfig) -> None:
    """件名に話数が明示されている場合、投稿タイトルは「作品名 ~ 話数」形式で作成される。"""
    mail = _make_mail(title="お菓子外しさんとカタカナ男", number=41)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        _, kwargs = mock_wp.create_post.call_args
        assert kwargs["title"] == "お菓子外しさんとカタカナ男 ~ 41"
        mock_wp.find_latest_post_number.assert_not_called()


def test_application_auto_numbers_from_latest_existing_post(app_config: AppConfig) -> None:
    """話数が未指定の場合、WordPress上の同一作品名の最新話数+1を自動採番する。"""
    mail = _make_mail(title="AAAA", number=None)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)
        mock_wp.find_latest_post_number.return_value = 41

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_wp.find_latest_post_number.assert_called_once_with("AAAA")
        _, kwargs = mock_wp.create_post.call_args
        assert kwargs["title"] == "AAAA ~ 42"


def test_application_auto_numbers_starts_at_one_when_no_existing_posts(app_config: AppConfig) -> None:
    """既存記事が1件も無い場合は第1話として採番する。"""
    mail = _make_mail(title="AAAA", number=None)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)
        mock_wp.find_latest_post_number.return_value = None

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        _, kwargs = mock_wp.create_post.call_args
        assert kwargs["title"] == "AAAA ~ 1"


def test_application_auto_numbered_prev_link_searches_previous_number(app_config: AppConfig) -> None:
    """自動採番で第42話になった場合も、前回記事として「AAAA ~ 41」を検索する。"""
    mail = _make_mail(title="AAAA", number=None)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)
        mock_wp.find_latest_post_number.return_value = 41
        mock_wp.find_post_by_title.return_value = ("https://example.com/?p=41", "AAAA ~ 41")

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_wp.find_post_by_title.assert_called_once_with("AAAA ~ 41")


def test_application_number_resolution_happens_before_image_upload(app_config: AppConfig) -> None:
    """最新話数検索の失敗時は、画像アップロード・記事投稿・履歴保存を一切行わない。"""
    mail = _make_mail(title="AAAA", number=None)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)
        mock_wp.find_latest_post_number.side_effect = Exception("WordPress API Error")

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_wp.upload_media.assert_not_called()
        mock_wp.get_or_create_category.assert_not_called()
        mock_wp.create_post.assert_not_called()
        mock_history.save.assert_not_called()


def test_application_prev_link_prefers_new_format(app_config: AppConfig) -> None:
    """前回記事検索は標準形式「作品名 ~ 40」を優先して使用する。"""
    mail = _make_mail(title="お菓子外しさんとカタカナ男", number=41)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)
        mock_wp.find_post_by_title.return_value = (
            "https://example.com/?p=40",
            "お菓子外しさんとカタカナ男 ~ 40",
        )

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_wp.find_post_by_title.assert_called_once_with("お菓子外しさんとカタカナ男 ~ 40")


def test_application_prev_link_falls_back_to_legacy_format(app_config: AppConfig) -> None:
    """標準形式で見つからない場合のみ、旧形式（No40 / No 40）へフォールバック検索する。"""
    mail = _make_mail(title="お菓子外しさんとカタカナ男", number=41)
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)
        mock_wp.find_post_by_title.side_effect = [
            (None, None),
            (None, None),
            ("https://example.com/?p=40", "お菓子外しさんとカタカナ男 No 40"),
        ]

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        assert mock_wp.find_post_by_title.call_args_list == [
            call("お菓子外しさんとカタカナ男 ~ 40"),
            call("お菓子外しさんとカタカナ男 No40"),
            call("お菓子外しさんとカタカナ男 No 40"),
        ]


def test_application_uploads_multiple_images_in_order(app_config: AppConfig) -> None:
    """複数添付画像が期待順（ファイル名昇順）でWordPressへアップロードされる。"""
    mail = _make_mail(filenames=["IMG0002.jpg", "IMG0001.jpg", "IMG0003.jpg"])
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        uploaded_names = [c.args[0].name for c in mock_wp.upload_media.call_args_list]
        assert uploaded_names == ["IMG0001.jpg", "IMG0002.jpg", "IMG0003.jpg"]


def test_application_handles_img_number_rollover(app_config: AppConfig) -> None:
    """IMG9999→IMG0001のロールオーバー順がWordPressアップロード順に維持される。"""
    mail = _make_mail(filenames=["IMG0001.jpg", "IMG0002.jpg", "IMG9998.jpg", "IMG9999.jpg"])
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        uploaded_names = [c.args[0].name for c in mock_wp.upload_media.call_args_list]
        assert uploaded_names == ["IMG9998.jpg", "IMG9999.jpg", "IMG0001.jpg", "IMG0002.jpg"]


def test_application_skips_when_no_supported_images(app_config: AppConfig) -> None:
    """対応形式の添付画像が1枚もない場合、投稿・履歴保存を行わずスキップする。"""
    mail = _make_mail(filenames=["memo.txt"])
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp, \
         patch("src.application.HistoryManager") as MockHistory:

        mock_gmail = MockGmail.return_value
        mock_gmail.fetch_unread.return_value = [mail]

        mock_wp = MockWp.return_value
        _setup_wp_mock(mock_wp)

        mock_history = MockHistory.return_value
        mock_history.find_by_message_id.return_value = None

        app.run()

        mock_wp.create_post.assert_not_called()
        mock_history.save.assert_not_called()


def test_application_skips_on_wp_failure(app_config: AppConfig) -> None:
    """異常系: WP投稿失敗時は履歴を保存せず次のメールへ継続する。"""
    mail = _make_mail()
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


def test_application_skips_duplicate_mail(app_config: AppConfig) -> None:
    """重複防止: 履歴に既存のmessage_idが見つかった場合は添付保存・投稿処理をスキップする。"""
    mail = _make_mail()
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

        image_dir = Path(app_config.paths.image_dir)
        assert list(image_dir.glob("*.jpg")) == []


def test_application_orders_mails_by_received_at_ascending(app_config: AppConfig) -> None:
    """Gmail一覧の返却順が不規則でも、受信時刻(received_at_ms)の古い順に直列投稿する。"""
    mail_42 = _make_mail(message_id="m-42", filenames=["IMG0042.jpg"], title="AAAA", number=42, received_at_ms=300)
    mail_40 = _make_mail(message_id="m-40", filenames=["IMG0040.jpg"], title="AAAA", number=40, received_at_ms=100)
    mail_41 = _make_mail(message_id="m-41", filenames=["IMG0041.jpg"], title="AAAA", number=41, received_at_ms=200)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient(existing_titles=["AAAA ~ 39"])

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_42, mail_40, mail_41]

        app.run()

    posted_titles = [p["title"] for p in fake_wp.created_posts]
    assert posted_titles == ["AAAA ~ 40", "AAAA ~ 41", "AAAA ~ 42"]


def test_application_stable_sort_keeps_relative_order_for_equal_timestamps(app_config: AppConfig) -> None:
    """同一received_at_msのメールは、取得時の相対順を維持する。"""
    mail_a = _make_mail(message_id="m-a", filenames=["IMG0001.jpg"], title="AAAA", number=1, received_at_ms=100)
    mail_b = _make_mail(message_id="m-b", filenames=["IMG0002.jpg"], title="BBBB", number=1, received_at_ms=100)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient()

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_a, mail_b]

        app.run()

    posted_titles = [p["title"] for p in fake_wp.created_posts]
    assert posted_titles == ["AAAA ~ 1", "BBBB ~ 1"]


def test_application_places_unknown_received_at_last_and_keeps_their_relative_order(app_config: AppConfig) -> None:
    """received_at_ms=Noneのメールは判明メールの後ろへ回り、時刻不明同士は取得時の相対順を維持する。"""
    mail_unknown_1 = _make_mail(message_id="m-u1", filenames=["IMG0001.jpg"], title="UUUU", number=1, received_at_ms=None)
    mail_unknown_2 = _make_mail(message_id="m-u2", filenames=["IMG0002.jpg"], title="UUUU", number=2, received_at_ms=None)
    mail_known = _make_mail(message_id="m-k", filenames=["IMG0003.jpg"], title="KKKK", number=1, received_at_ms=100)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient()

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_unknown_1, mail_unknown_2, mail_known]

        app.run()

    posted_titles = [p["title"] for p in fake_wp.created_posts]
    assert posted_titles == ["KKKK ~ 1", "UUUU ~ 1", "UUUU ~ 2"]


def test_application_multi_mail_case1_irregular_order_links_same_run_previous(app_config: AppConfig) -> None:
    """ケース1: API返却順が不規則でも、受信時刻順に投稿し、同一実行で投稿した直前話をリンクする。"""
    mail_42 = _make_mail(message_id="m-42", filenames=["IMG0042.jpg"], title="AAAA", number=42, received_at_ms=1010)
    mail_40 = _make_mail(message_id="m-40", filenames=["IMG0040.jpg"], title="AAAA", number=40, received_at_ms=1000)
    mail_41 = _make_mail(message_id="m-41", filenames=["IMG0041.jpg"], title="AAAA", number=41, received_at_ms=1005)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient()

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_42, mail_40, mail_41]

        app.run()

    posts_by_title = {p["title"]: p for p in fake_wp.created_posts}
    assert list(posts_by_title) == ["AAAA ~ 40", "AAAA ~ 41", "AAAA ~ 42"]
    assert "AAAA ~ 40" not in posts_by_title["AAAA ~ 40"]["content"]  # 第1話相当。前回セクションなし
    assert "AAAA ~ 40" in posts_by_title["AAAA ~ 41"]["content"]
    assert "AAAA ~ 41" in posts_by_title["AAAA ~ 42"]["content"]


def test_application_multi_mail_case2_previous_links_do_not_cross_series(app_config: AppConfig) -> None:
    """ケース2: 複数作品が混在しても、前回リンクが作品間で交差しない。"""
    mail_aaaa_41 = _make_mail(message_id="m-a41", filenames=["IMG0001.jpg"], title="AAAA", number=41, received_at_ms=1000)
    mail_bbbb_11 = _make_mail(message_id="m-b11", filenames=["IMG0002.jpg"], title="BBBB", number=11, received_at_ms=1005)
    mail_aaaa_42 = _make_mail(message_id="m-a42", filenames=["IMG0003.jpg"], title="AAAA", number=42, received_at_ms=1010)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient(existing_titles=["AAAA ~ 40", "BBBB ~ 10"])

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_aaaa_41, mail_bbbb_11, mail_aaaa_42]

        app.run()

    posts_by_title = {p["title"]: p for p in fake_wp.created_posts}
    assert "AAAA ~ 40" in posts_by_title["AAAA ~ 41"]["content"]
    assert "BBBB ~ 10" in posts_by_title["BBBB ~ 11"]["content"]
    assert "AAAA ~ 41" in posts_by_title["AAAA ~ 42"]["content"]
    # 作品間の交差が無いこと
    assert "BBBB" not in posts_by_title["AAAA ~ 41"]["content"]
    assert "AAAA" not in posts_by_title["BBBB ~ 11"]["content"]


def test_application_multi_mail_case3_auto_numbering_across_run_is_sequential(app_config: AppConfig) -> None:
    """ケース3: 話数省略メール複数件でも、受信時刻順に採番し重複しない。"""
    mail_1 = _make_mail(message_id="m-1", filenames=["IMG0001.jpg"], title="AAAA", number=None, received_at_ms=1000)
    mail_2 = _make_mail(message_id="m-2", filenames=["IMG0002.jpg"], title="AAAA", number=None, received_at_ms=1005)
    mail_3 = _make_mail(message_id="m-3", filenames=["IMG0003.jpg"], title="AAAA", number=None, received_at_ms=1010)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient(existing_titles=["AAAA ~ 40"])

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_1, mail_2, mail_3]

        app.run()

    posts_by_title = {p["title"]: p for p in fake_wp.created_posts}
    assert list(posts_by_title) == ["AAAA ~ 41", "AAAA ~ 42", "AAAA ~ 43"]
    assert "AAAA ~ 40" in posts_by_title["AAAA ~ 41"]["content"]
    assert "AAAA ~ 41" in posts_by_title["AAAA ~ 42"]["content"]
    assert "AAAA ~ 42" in posts_by_title["AAAA ~ 43"]["content"]


def test_application_multi_mail_case4_first_episode_has_no_previous_section(app_config: AppConfig) -> None:
    """ケース4: 第1話は前回検索を行わず、前回セクションを一切生成しない。"""
    mail = _make_mail(message_id="m-1", filenames=["IMG0001.jpg"], title="CCCC", number=1, received_at_ms=1000)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient()

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail]

        app.run()

    assert len(fake_wp.created_posts) == 1
    content = fake_wp.created_posts[0]["content"]
    assert "■前回のお話はこちら" not in content
    assert "<!-- 前回の話 -->" not in content


def test_application_multi_mail_case5_missing_previous_episode_has_no_section(app_config: AppConfig) -> None:
    """ケース5: 直前話が欠番の場合、それより前の話へ遡らず前回セクションを生成しない。"""
    mail = _make_mail(message_id="m-42", filenames=["IMG0001.jpg"], title="DDDD", number=42, received_at_ms=1000)

    app = Application(app_config)
    # DDDD ~ 40は存在するが、直前の DDDD ~ 41 は存在しない（欠番）
    fake_wp = _FakeWordPressClient(existing_titles=["DDDD ~ 40"])

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail]

        app.run()

    assert len(fake_wp.created_posts) == 1
    content = fake_wp.created_posts[0]["content"]
    assert "DDDD ~ 40" not in content
    assert "■前回のお話はこちら" not in content


def test_application_multi_mail_case6_failed_post_not_cached_or_linked(app_config: AppConfig) -> None:
    """ケース6: 投稿失敗記事は実行中キャッシュへ登録されず、後続記事からリンクされない。履歴も未保存。"""
    mail_41 = _make_mail(message_id="m-41", filenames=["IMG0041.jpg"], title="AAAA", number=41, received_at_ms=1000)
    mail_42 = _make_mail(message_id="m-42", filenames=["IMG0042.jpg"], title="AAAA", number=42, received_at_ms=1005)

    app = Application(app_config)
    fake_wp = _FakeWordPressClient()
    fake_wp.fail_titles.add("AAAA ~ 41")

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient", return_value=fake_wp):
        MockGmail.return_value.fetch_unread.return_value = [mail_41, mail_42]

        app.run()

    posts_by_title = {p["title"]: p for p in fake_wp.created_posts}
    assert "AAAA ~ 41" not in posts_by_title  # 投稿失敗のため作成されない
    assert "AAAA ~ 42" in posts_by_title
    assert "AAAA ~ 41" not in posts_by_title["AAAA ~ 42"]["content"]
    assert "■前回のお話はこちら" not in posts_by_title["AAAA ~ 42"]["content"]

    from src.history_manager import HistoryManager
    history = HistoryManager(app_config.paths.history_file)
    assert history.find_by_message_id("m-41") is None
    assert history.find_by_message_id("m-42") is not None


def test_application_no_mails(app_config: AppConfig) -> None:
    """メールがない場合は何も投稿しない。"""
    app = Application(app_config)

    with patch("src.application.GmailClient") as MockGmail, \
         patch("src.application.WordPressClient") as MockWp:

        MockGmail.return_value.fetch_unread.return_value = []
        app.run()
        MockWp.return_value.create_post.assert_not_called()
