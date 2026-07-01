"""WordPress REST API を利用してメディアアップロード・カテゴリ管理・記事投稿を行うモジュール。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

from src.config_manager import WordPressConfig

logger = logging.getLogger(__name__)

_MEDIA_ENDPOINT = "/wp-json/wp/v2/media"
_POSTS_ENDPOINT = "/wp-json/wp/v2/posts"
_CATEGORIES_ENDPOINT = "/wp-json/wp/v2/categories"


class WordPressError(Exception):
    """WordPress API 呼び出しに起因するエラー。"""


class WordPressClient:
    """WordPress REST API クライアント。

    認証は Application Password による HTTP Basic 認証を使用する。
    通信エラー・429・一時的な 5xx は指数バックオフで最大 max_retries 回リトライする。
    """

    def __init__(self, config: WordPressConfig, max_retries: int = 3, initial_wait: float = 2.0) -> None:
        self._base_url = config.url.rstrip("/")
        self._auth = HTTPBasicAuth(config.username, config.application_password)
        self._default_status = config.default_status
        self._max_retries = max_retries
        self._initial_wait = initial_wait

    # ------------------------------------------------------------------
    # パブリックAPI
    # ------------------------------------------------------------------

    def upload_media(self, image_path: Path) -> tuple[int, str]:
        """画像ファイルをメディアライブラリへアップロードする。

        Returns:
            (media_id, url) のタプル。
        Raises:
            WordPressError: アップロード失敗時。
        """
        url = self._base_url + _MEDIA_ENDPOINT
        mime = "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        headers = {"Content-Disposition": f'attachment; filename="{image_path.name}"'}

        with image_path.open("rb") as f:
            data = f.read()

        resp = self._request_with_retry(
            "POST", url,
            headers=headers,
            data=data,
            content_type=mime,
        )
        media_id: int = resp["id"]
        media_url: str = resp["source_url"]
        logger.info("メディアアップロード完了: id=%s url=%s", media_id, media_url)
        return media_id, media_url

    def get_or_create_category(self, name: str) -> int:
        """カテゴリ名でIDを検索し、存在しなければ作成して返す。

        Returns:
            category_id
        Raises:
            WordPressError: API呼び出し失敗時。
        """
        category_id = self._find_category(name)
        if category_id is not None:
            logger.info("カテゴリ取得: %s (id=%s)", name, category_id)
            return category_id

        url = self._base_url + _CATEGORIES_ENDPOINT
        resp = self._request_with_retry("POST", url, json={"name": name})
        category_id = resp["id"]
        logger.info("カテゴリ作成: %s (id=%s)", name, category_id)
        return category_id

    def find_post_by_title(self, title: str) -> tuple[str | None, str | None]:
        """完全一致タイトルで記事を検索し (url, title) を返す。見つからなければ (None, None)。"""
        url = self._base_url + _POSTS_ENDPOINT
        params = {"search": title, "per_page": 10, "status": "any"}
        resp = self._session_get(url, params=params)
        for post in resp.json():
            rendered = post.get("title", {}).get("rendered", "")
            if rendered == title:
                return post["link"], rendered
        return None, None

    def find_latest_post_number(self, title_prefix: str) -> int | None:
        """タイトルプレフィックスで記事を検索し、最大の連番を返す。

        Returns:
            最大連番。記事が存在しない場合は None。
        """
        import re
        url = self._base_url + _POSTS_ENDPOINT
        params = {"search": title_prefix, "per_page": 100, "status": "any"}
        resp = self._session_get(url, params=params)
        posts: list[dict] = resp.json()

        pattern = re.compile(rf"^{re.escape(title_prefix)}\s+No(\d+)", re.IGNORECASE)
        numbers: list[int] = []
        for post in posts:
            m = pattern.match(post.get("title", {}).get("rendered", ""))
            if m:
                numbers.append(int(m.group(1)))

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
        """記事を投稿する。

        Args:
            title: 投稿タイトル。
            content: 投稿本文HTML。
            category_id: カテゴリID。
            featured_media_id: アイキャッチ画像のメディアID。
            status: publish / draft / future。None の場合は config の default_status を使用。
            scheduled_at: 予約投稿日時（ISO 8601 または "YYYY/MM/DD HH:MM"）。
        Returns:
            (post_id, post_url) のタプル。
        Raises:
            WordPressError: 投稿失敗時。
        """
        post_status = status or self._default_status
        payload: dict = {
            "title": title,
            "content": content,
            "status": post_status,
            "categories": [category_id],
        }
        if featured_media_id is not None:
            payload["featured_media"] = featured_media_id
        if scheduled_at:
            payload["date"] = self._normalize_datetime(scheduled_at)
            payload["status"] = "future"

        url = self._base_url + _POSTS_ENDPOINT
        resp = self._request_with_retry("POST", url, json=payload)
        post_id: int = resp["id"]
        post_url: str = resp["link"]
        logger.info("記事投稿完了: id=%s url=%s", post_id, post_url)
        return post_id, post_url

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _find_category(self, name: str) -> int | None:
        url = self._base_url + _CATEGORIES_ENDPOINT
        params = {"search": name, "per_page": 100}
        resp = self._session_get(url, params=params)
        for cat in resp.json():
            if cat.get("name") == name:
                return int(cat["id"])
        return None

    def _request_with_retry(
        self,
        method: str,
        url: str,
        content_type: str | None = None,
        **kwargs,
    ) -> dict:
        """リトライ付きリクエストを実行し、レスポンスJSONを返す。"""
        headers = kwargs.pop("headers", {})
        if content_type:
            headers["Content-Type"] = content_type

        wait = self._initial_wait
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.request(
                    method, url,
                    auth=self._auth,
                    headers=headers,
                    timeout=30,
                    **kwargs,
                )
                if resp.status_code in {429} or (500 <= resp.status_code < 600):
                    raise WordPressError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, WordPressError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    logger.warning("リトライ (%d/%d): %s", attempt, self._max_retries, exc)
                    time.sleep(wait)
                    wait *= 2
                else:
                    logger.error("リトライ上限到達: %s", exc)

        raise WordPressError(f"最大リトライ回数({self._max_retries})を超えました: {last_exc}")

    def _session_get(self, url: str, params: dict | None = None) -> requests.Response:
        """認証付き GET リクエスト（リトライなし）。"""
        resp = requests.get(url, auth=self._auth, params=params, timeout=30)
        resp.raise_for_status()
        return resp

    @staticmethod
    def _normalize_datetime(value: str) -> str:
        """WordPress が受け付ける ISO 8601 形式に変換する。

        対応形式:
            2026/07/10 20:00  →  2026-07-10T20:00:00
            2026-07-10T20:00:00  →  そのまま
        """
        import re
        m = re.match(r"(\d{4})[/-](\d{2})[/-](\d{2})\s+(\d{2}):(\d{2})", value)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:00"
        return value
