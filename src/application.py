"""アプリケーション全体フローを制御するモジュール。"""

from __future__ import annotations

import logging
from pathlib import Path

from src.attachment_manager import AttachmentManager
from src.config_manager import AppConfig, ConfigManager
from src.gmail_client import GmailClient
from src.history_manager import HistoryManager, PostHistory
from src.html_generator import HtmlGenerator
from src.image_sorter import ImageSorter
from src.log_manager import LogManager
from src.models import MailData
from src.wordpress_client import WordPressClient

logger = logging.getLogger(__name__)


class Application:
    """Gmail取得からWordPress投稿完了までの全体フローを制御する。

    処理単位: メール1件ずつ独立して処理する。
    ロールバック方針: 投稿失敗時は投稿履歴を保存せず、次回実行時に再試行する。
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def run(self) -> None:
        """メイン処理を実行する。"""
        cfg = self._config
        logger.info("=== Application Start ===")

        gmail = GmailClient(cfg.gmail)
        wp = WordPressClient(
            cfg.wordpress,
            max_retries=cfg.retry.max_count,
            initial_wait=float(cfg.retry.initial_wait_seconds),
        )
        attachment_mgr = AttachmentManager(cfg.paths.image_dir)
        sorter = ImageSorter()
        html_gen = HtmlGenerator(cfg.paths.template)
        history_mgr = HistoryManager(cfg.paths.history_file)

        try:
            gmail.connect()
            mails = gmail.fetch_unread()
            logger.info("%d 件のメールを取得しました", len(mails))

            if not mails:
                logger.info("処理対象メールなし。終了します。")
                return

            for mail in mails:
                self._process_mail(mail, wp, attachment_mgr, sorter, html_gen, history_mgr)

        except Exception as exc:
            logger.error("予期しない例外が発生しました: %s", exc, exc_info=True)
            raise
        finally:
            gmail.disconnect()
            logger.info("=== Application End ===")

    def _process_mail(
        self,
        mail: MailData,
        wp: WordPressClient,
        attachment_mgr: AttachmentManager,
        sorter: ImageSorter,
        html_gen: HtmlGenerator,
        history_mgr: HistoryManager,
    ) -> None:
        """メール1件を処理する。失敗時は例外をキャッチしてスキップする（ロールバック）。

        gmail.readonlyスコープでは既読化・ラベル付与ができないため、
        処理済みメールの重複判定は投稿履歴（HistoryManager）のmail_message_idで行う。
        """
        logger.info("--- 処理開始: %s ---", mail.subject)

        if history_mgr.find_by_message_id(mail.message_id) is not None:
            logger.info("処理済みメールをスキップ: %s", mail.subject)
            return

        try:
            post_id, post_url = self._execute(mail, wp, attachment_mgr, sorter, html_gen)

            # --- 投稿成功後のみ実行 ---
            history_mgr.save(PostHistory(
                post_id=post_id,
                title=mail.title,
                category=mail.category,
                created_at=mail.scheduled_at or "",
                mail_message_id=mail.message_id,
            ))
            logger.info("投稿完了: id=%s url=%s", post_id, post_url)

        except Exception as exc:
            logger.error("メール処理失敗（スキップ）: %s / %s", mail.subject, exc, exc_info=True)

    def _execute(
        self,
        mail: MailData,
        wp: WordPressClient,
        attachment_mgr: AttachmentManager,
        sorter: ImageSorter,
        html_gen: HtmlGenerator,
    ) -> tuple[int, str]:
        """添付取得〜WordPress投稿までの処理を実行し (post_id, post_url) を返す。"""

        # 1. 添付画像ソート（MailData に保存済みパスを使用）
        image_paths = sorter.sort(mail.attachment_paths)
        if not image_paths:
            raise ValueError(f"添付画像が存在しません: {mail.subject}")

        # 2. 画像アップロード
        media_ids: list[int] = []
        media_urls: list[str] = []
        for path in image_paths:
            media_id, url = wp.upload_media(path)
            media_ids.append(media_id)
            media_urls.append(url)

        # 3. カテゴリ取得・作成
        category_id = wp.get_or_create_category(mail.category)

        # 4. 記事番号採番
        number = mail.number
        if number is None:
            latest = wp.find_latest_post_number(mail.title)
            number = (latest or 0) + 1

        # 5. 前回記事検索（採番した番号 - 1）
        prev_url: str | None = None
        prev_title: str | None = None
        if number > 1:
            prev_number = number - 1
            prev_title_full = f"{mail.title} No{prev_number}"
            prev_url, prev_title = wp.find_post_by_title(prev_title_full)

        # 6. HTML生成
        full_title = f"{mail.title} No{number}"
        html = html_gen.generate(
            image_urls=media_urls,
            prev_url=prev_url,
            prev_title=prev_title,
        )

        # 7. 記事投稿（1枚目画像をアイキャッチに設定）
        post_id, post_url = wp.create_post(
            title=full_title,
            content=html,
            category_id=category_id,
            featured_media_id=media_ids[0] if media_ids else None,
            scheduled_at=mail.scheduled_at,
        )
        return post_id, post_url



def create_application(config_path: str = "config/config.yaml") -> Application:
    """設定ファイルを読み込み Application インスタンスを返すファクトリ関数。"""
    manager = ConfigManager(config_path)
    config = manager.load()

    log_manager = LogManager(config.paths.log_file, level=config.log_level)
    log_manager.setup()

    return Application(config)
