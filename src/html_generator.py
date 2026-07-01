"""template.html を読み込み、前回記事リンクと画像HTMLを差し込んで投稿本文を生成するモジュール。"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PLACEHOLDER_PREV = "<!-- 前回の話 -->"
_PLACEHOLDER_BODY = "<!-- 以下本文 -->"


def _build_prev_link_html(prev_url: str, prev_title: str) -> str:
    return (
        f'<p>■前回のお話はこちら<br>'
        f'<a href="{prev_url}">{prev_title}</a></p>'
    )


def _build_images_html(image_urls: list[str]) -> str:
    parts = []
    for url in image_urls:
        parts.append(f'<figure class="wp-block-image"><img src="{url}" /></figure>')
    return "\n".join(parts)


class HtmlGenerator:
    """template.html のプレースホルダーを実際のコンテンツへ置換してHTML本文を生成する。"""

    def __init__(self, template_path: str | Path) -> None:
        self._template_path = Path(template_path)

    def generate(
        self,
        image_urls: list[str],
        prev_url: str | None = None,
        prev_title: str | None = None,
    ) -> str:
        """投稿本文HTMLを生成して返す。

        Args:
            image_urls: アップロード済み画像のURLリスト（順序を保持）。
            prev_url: 前回記事のURL。None の場合はプレースホルダーを削除する。
            prev_title: 前回記事のタイトル。
        Returns:
            差し込み済みのHTML文字列。
        Raises:
            FileNotFoundError: テンプレートファイルが存在しない場合。
        """
        if not self._template_path.exists():
            raise FileNotFoundError(f"テンプレートが見つかりません: {self._template_path}")

        template = self._template_path.read_text(encoding="utf-8")

        # 前回記事リンクの差し込み
        if prev_url and prev_title:
            prev_html = _build_prev_link_html(prev_url, prev_title)
            logger.info("前回記事リンクを挿入: %s", prev_url)
        else:
            prev_html = ""
            logger.info("前回記事なし: プレースホルダーを削除")
        template = template.replace(_PLACEHOLDER_PREV, prev_html)

        # 画像HTMLの差し込み
        images_html = _build_images_html(image_urls)
        template = template.replace(_PLACEHOLDER_BODY, images_html)

        return template
