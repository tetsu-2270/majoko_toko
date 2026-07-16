from __future__ import annotations

from pathlib import Path
from typing import Union
from unittest.mock import MagicMock, patch

import pytest

from src.config_manager import WordPressConfig
from src.wordpress_client import WordPressClient, WordPressError


@pytest.fixture
def wp_config() -> WordPressConfig:
    return WordPressConfig(
        url="https://example.com",
        username="wp_user",
        application_password="dummy",
        default_status="draft",
        default_category="Blog",
    )


@pytest.fixture
def client(wp_config: WordPressConfig) -> WordPressClient:
    return WordPressClient(wp_config, max_retries=3, initial_wait=0)


def _mock_response(json_data: Union[dict, list], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestUploadMedia:
    def test_returns_id_and_url(self, client: WordPressClient, tmp_path: Path) -> None:
        img = tmp_path / "IMG0001.jpg"
        img.write_bytes(b"\xff\xd8\xff")

        with patch("src.wordpress_client.requests.request") as mock_req:
            mock_req.return_value = _mock_response({"id": 10, "source_url": "https://example.com/img.jpg"}, 201)
            media_id, url = client.upload_media(img)

        assert media_id == 10
        assert url == "https://example.com/img.jpg"

    def test_retries_on_429(self, client: WordPressClient, tmp_path: Path) -> None:
        img = tmp_path / "IMG0001.jpg"
        img.write_bytes(b"\xff\xd8\xff")

        rate_limited = _mock_response({}, 429)
        success = _mock_response({"id": 5, "source_url": "https://example.com/x.jpg"}, 201)

        with patch("src.wordpress_client.requests.request", side_effect=[rate_limited, success]):
            media_id, _ = client.upload_media(img)

        assert media_id == 5

    def test_raises_after_max_retries(self, client: WordPressClient, tmp_path: Path) -> None:
        img = tmp_path / "IMG0001.jpg"
        img.write_bytes(b"\xff\xd8\xff")

        rate_limited = _mock_response({}, 429)
        with patch("src.wordpress_client.requests.request", return_value=rate_limited):
            with pytest.raises(WordPressError):
                client.upload_media(img)


class TestGetOrCreateCategory:
    def test_returns_existing_category(self, client: WordPressClient) -> None:
        cats = [{"id": 3, "name": "4コマ"}]

        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(cats)
            cat_id = client.get_or_create_category("4コマ")

        assert cat_id == 3

    def test_creates_new_category(self, client: WordPressClient) -> None:
        with patch("src.wordpress_client.requests.get") as mock_get, \
             patch("src.wordpress_client.requests.request") as mock_req:
            mock_get.return_value = _mock_response([])
            mock_req.return_value = _mock_response({"id": 7, "name": "新カテゴリ"}, 201)
            cat_id = client.get_or_create_category("新カテゴリ")

        assert cat_id == 7


class TestCreatePost:
    def test_returns_post_id_and_url(self, client: WordPressClient) -> None:
        with patch("src.wordpress_client.requests.request") as mock_req:
            mock_req.return_value = _mock_response(
                {"id": 100, "link": "https://example.com/?p=100"}, 201
            )
            post_id, post_url = client.create_post(
                title="テスト No1",
                content="<p>本文</p>",
                category_id=3,
                featured_media_id=10,
            )

        assert post_id == 100
        assert post_url == "https://example.com/?p=100"

    def test_scheduled_post_sets_future_status(self, client: WordPressClient) -> None:
        with patch("src.wordpress_client.requests.request") as mock_req:
            mock_req.return_value = _mock_response({"id": 101, "link": "https://example.com/?p=101"}, 201)
            client.create_post(
                title="予約 No1",
                content="<p>本文</p>",
                category_id=3,
                scheduled_at="2026/07/10 20:00",
            )
            _, kwargs = mock_req.call_args
            body = kwargs.get("json", {})

        assert body.get("status") == "future"
        assert body.get("date") == "2026-07-10T20:00:00"


class TestFindPostByTitle:
    def test_returns_exact_match(self, client: WordPressClient) -> None:
        posts = [{"title": {"rendered": "AAAA ~ 41"}, "link": "https://example.com/?p=41"}]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            url, title = client.find_post_by_title("AAAA ~ 41")

        assert url == "https://example.com/?p=41"
        assert title == "AAAA ~ 41"

    def test_ignores_partial_matches(self, client: WordPressClient) -> None:
        """部分一致・接頭辞違いのタイトルを採用せず、完全一致のみを採用する。"""
        posts = [
            {"title": {"rendered": "AAAA番外編 ~ 41"}, "link": "https://example.com/?p=1"},
            {"title": {"rendered": "AAAA ~ 410"}, "link": "https://example.com/?p=2"},
            {"title": {"rendered": "AAAA ~ 41"}, "link": "https://example.com/?p=3"},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            url, title = client.find_post_by_title("AAAA ~ 41")

        assert url == "https://example.com/?p=3"
        assert title == "AAAA ~ 41"

    def test_matches_after_html_entity_unescape(self, client: WordPressClient) -> None:
        """WordPressがHTMLエンティティ化して返したタイトルも、アンエスケープ後に一致すれば採用する。"""
        posts = [{"title": {"rendered": "AAAA &#8211; 41"}, "link": "https://example.com/?p=1"}]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            url, title = client.find_post_by_title("AAAA – 41")

        assert url == "https://example.com/?p=1"
        assert title == "AAAA &#8211; 41"

    def test_returns_none_when_not_found(self, client: WordPressClient) -> None:
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response([])
            url, title = client.find_post_by_title("AAAA ~ 41")

        assert (url, title) == (None, None)


class TestFindLatestPostNumber:
    def test_recognizes_new_tilde_format(self, client: WordPressClient) -> None:
        posts = [
            {"title": {"rendered": "お菓子外しさんとカタカナ男 ~ 39"}},
            {"title": {"rendered": "お菓子外しさんとカタカナ男 ~ 40"}},
            {"title": {"rendered": "お菓子外しさんとカタカナ男 ~ 41"}},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            result = client.find_latest_post_number("お菓子外しさんとカタカナ男")

        assert result == 41

    def test_recognizes_legacy_no_format(self, client: WordPressClient) -> None:
        posts = [
            {"title": {"rendered": "お菓子外しさんとカタカナ男 No39"}},
            {"title": {"rendered": "お菓子外しさんとカタカナ男 No 40"}},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            result = client.find_latest_post_number("お菓子外しさんとカタカナ男")

        assert result == 40

    def test_mixed_new_and_legacy_formats_returns_max(self, client: WordPressClient) -> None:
        posts = [
            {"title": {"rendered": "お菓子外しさんとカタカナ男 No39"}},
            {"title": {"rendered": "お菓子外しさんとカタカナ男 ~ 40"}},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            result = client.find_latest_post_number("お菓子外しさんとカタカナ男")

        assert result == 40

    def test_ignores_malformed_title(self, client: WordPressClient) -> None:
        """誤って作成された「作品名 41 No1」形式は採番対象としない。"""
        posts = [
            {"title": {"rendered": "お菓子外しさんとカタカナ男 41 No1"}},
            {"title": {"rendered": "お菓子外しさんとカタカナ男 ~ 5"}},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            result = client.find_latest_post_number("お菓子外しさんとカタカナ男")

        assert result == 5

    def test_excludes_different_title_with_longer_prefix(self, client: WordPressClient) -> None:
        """検索対象より長い別作品名（例: "AAAAA"）は"AAAA"の採番対象に含めない。"""
        posts = [
            {"title": {"rendered": "AAAAA ~ 100"}},
            {"title": {"rendered": "AAAA ~ 5"}},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            result = client.find_latest_post_number("AAAA")

        assert result == 5

    def test_excludes_title_with_extra_word_after_prefix(self, client: WordPressClient) -> None:
        """作品名の直後に区切り以外の文字列が続くタイトル（例: "AAAA テスト ~ 50"）は対象外とする。"""
        posts = [
            {"title": {"rendered": "AAAA テスト ~ 50"}},
            {"title": {"rendered": "AAAA ~ 5"}},
        ]
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(posts)
            result = client.find_latest_post_number("AAAA")

        assert result == 5

    def test_returns_none_when_no_matching_posts(self, client: WordPressClient) -> None:
        with patch("src.wordpress_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response([])
            result = client.find_latest_post_number("お菓子外しさんとカタカナ男")

        assert result is None


class TestNormalizeDatetime:
    def test_slash_format(self) -> None:
        result = WordPressClient._normalize_datetime("2026/07/10 20:00")
        assert result == "2026-07-10T20:00:00"

    def test_hyphen_format(self) -> None:
        result = WordPressClient._normalize_datetime("2026-07-10 20:00")
        assert result == "2026-07-10T20:00:00"

    def test_iso_passthrough(self) -> None:
        result = WordPressClient._normalize_datetime("2026-07-10T20:00:00")
        assert result == "2026-07-10T20:00:00"


def test_wordpress_client_upload_media_mock(client: WordPressClient, tmp_path: Path) -> None:
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    with patch("src.wordpress_client.requests.request") as mock_req:
        mock_req.return_value = _mock_response({"id": 1, "source_url": "https://example.com/test.jpg"}, 201)
        media_id, url = client.upload_media(img)
    assert media_id == 1
