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

# 実行中の投稿成功記事を保持するキャッシュのキー: (作品名, 話数) → 値: (投稿タイトル, 投稿URL)
PostedArticles = dict[tuple[str, int], tuple[str, str]]


def format_article_title(title: str, number: int) -> str:
    """記事タイトルを標準形式「作品名 ~ 話数」へ整形する。

    話数が件名に明示されている場合・WordPress検索により自動採番された場合の
    いずれも、記事投稿・前回記事検索の両方でこの関数を使い、タイトル形式を一箇所へ集約する。
    """
    return f"{title} ~ {number}"


def _legacy_title_candidates(title: str, number: int) -> list[str]:
    """移行期間中に存在しうる旧タイトル形式（No形式）の、前回記事検索用フォールバック候補を返す。"""
    return [f"{title} No{number}", f"{title} No {number}"]


class Application:
    """Gmail取得からWordPress投稿完了までの全体フローを制御する。

    処理単位: Gmail受信時刻の古い順に並べ替えたうえで、メール1件ずつ直列に処理する
    （並列投稿は行わない）。同一実行中に投稿成功した記事は実行中キャッシュへ保持し、
    後続メールの自動採番・前回記事解決から参照できるようにする（WordPress検索結果へ
    直後に反映されない場合があるため）。
    ロールバック方針: 投稿失敗時は投稿履歴・実行中キャッシュのいずれにも登録せず、
    次回実行時に再試行する。後続メールの処理は受信時刻順のまま継続する。
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

            ordered_mails = self._order_by_received_at(mails)
            self._log_processing_order(ordered_mails)

            posted_articles: PostedArticles = {}
            for mail in ordered_mails:
                self._process_mail(mail, wp, attachment_mgr, sorter, html_gen, history_mgr, posted_articles)

        except Exception as exc:
            logger.error("予期しない例外が発生しました: %s", exc, exc_info=True)
            raise
        finally:
            gmail.disconnect()
            logger.info("=== Application End ===")

    @staticmethod
    def _order_by_received_at(mails: list[MailData]) -> list[MailData]:
        """Gmail受信時刻（`received_at_ms`）の古い順へ安定ソートする。

        受信時刻が判明しているメールを先に時刻昇順で並べ、時刻不明（`None`）のメールは
        判明メールの後ろへ回す。Pythonの`sorted()`は安定ソートのため、同一時刻同士・
        時刻不明同士は取得時（Gmail API一覧の返却順）の相対順を維持する。Gmail APIの
        一覧返却順そのものは投稿順として信頼しない。
        """
        return sorted(mails, key=lambda mail: (mail.received_at_ms is None, mail.received_at_ms or 0))

    @staticmethod
    def _log_processing_order(mails: list[MailData]) -> None:
        """確定した処理順をINFOログへ記録する（本文・添付内容・認証情報は出力しない）。"""
        for index, mail in enumerate(mails, start=1):
            logger.info(
                "処理順: %d received_at_ms=%s subject=%s message_id=%s",
                index, mail.received_at_ms, mail.subject, mail.message_id,
            )

    def _process_mail(
        self,
        mail: MailData,
        wp: WordPressClient,
        attachment_mgr: AttachmentManager,
        sorter: ImageSorter,
        html_gen: HtmlGenerator,
        history_mgr: HistoryManager,
        posted_articles: PostedArticles,
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
            post_id, post_url, number, full_title = self._execute(
                mail, wp, attachment_mgr, sorter, html_gen, posted_articles
            )

            # --- 投稿成功後のみ実行 ---
            posted_articles[(mail.title, number)] = (full_title, post_url)
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
        posted_articles: PostedArticles,
    ) -> tuple[int, str, int, str]:
        """添付取得〜WordPress投稿までの処理を実行し (post_id, post_url, number, full_title) を返す。

        話数は、件名に明示されていればそれを使用し、無ければWordPress上の同一作品名の
        最新話数と、同一実行中の投稿成功キャッシュの最新話数を比較していずれか大きい方+1を
        採番する（既存記事も実行中記事も無ければ第1話）。話数解決は画像アップロード・
        カテゴリ作成より前に行い、最新話数検索の失敗時にWordPressへ不要な画像やカテゴリが
        残らないようにする。
        """
        # 1. 話数解決（件名に明示されていればそれを使用、無ければ自動採番）
        number = self._resolve_number(mail, wp, posted_articles)

        # 2. 添付画像を保存し、ロールオーバー考慮で並び替え
        saved_paths = attachment_mgr.save(mail.attachments)
        image_paths = sorter.sort(saved_paths)
        if not image_paths:
            raise ValueError(f"添付画像が存在しません: {mail.subject}")

        # 3. 画像アップロード
        media_ids: list[int] = []
        media_urls: list[str] = []
        for path in image_paths:
            media_id, url = wp.upload_media(path)
            media_ids.append(media_id)
            media_urls.append(url)

        # 4. カテゴリ取得・作成
        category_id = wp.get_or_create_category(mail.category)

        # 5. 前回記事解決（同一作品の直前話のみ。実行中キャッシュ優先→WordPress標準形式→旧形式）
        prev_url, prev_title = self._resolve_previous_article(mail.title, number, wp, posted_articles)

        # 6. HTML生成
        full_title = format_article_title(mail.title, number)
        html_content = html_gen.generate(
            image_urls=media_urls,
            prev_url=prev_url,
            prev_title=prev_title,
        )

        # 7. 記事投稿（1枚目画像をアイキャッチに設定）
        post_id, post_url = wp.create_post(
            title=full_title,
            content=html_content,
            category_id=category_id,
            featured_media_id=media_ids[0] if media_ids else None,
            scheduled_at=mail.scheduled_at,
        )
        return post_id, post_url, number, full_title

    @staticmethod
    def _resolve_number(mail: MailData, wp: WordPressClient, posted_articles: PostedArticles) -> int:
        """話数を解決する。

        件名に話数が明示されていればそれをそのまま使用する。省略されている場合は、
        WordPress上の同一作品名の最新話数と、同一実行中に投稿成功した同一作品名の
        最新話数の両方を比較し、大きい方+1を採番する（WordPress検索結果が直前に
        作成した記事をすぐ反映しない場合でも、実行中キャッシュにより重複話数の採番を防ぐ）。
        既存記事・実行中記事のいずれも無ければ第1話とする。
        """
        if mail.number is not None:
            return mail.number

        wp_latest = wp.find_latest_post_number(mail.title)
        cache_latest = Application._latest_cached_number(mail.title, posted_articles)
        candidates = [n for n in (wp_latest, cache_latest) if n is not None]
        return (max(candidates) if candidates else 0) + 1

    @staticmethod
    def _latest_cached_number(title: str, posted_articles: PostedArticles) -> int | None:
        """同一実行中キャッシュから、同一作品名の最大話数を返す（無ければNone）。"""
        numbers = [number for (series_title, number) in posted_articles if series_title == title]
        return max(numbers) if numbers else None

    @staticmethod
    def _resolve_previous_article(
        title: str,
        number: int,
        wp: WordPressClient,
        posted_articles: PostedArticles,
    ) -> tuple[str | None, str | None]:
        """前回記事（同一作品名の直前話のみ）を解決し (url, title) を返す。見つからなければ (None, None)。

        解決順: (1) 同一実行中の投稿成功キャッシュ → (2) WordPress標準形式 →
        (3) WordPress旧No形式（フォールバック）。第1話（number<=1）の場合は検索を行わない。
        直前話が存在しない場合に、それより前の話数へ遡ることはしない。
        """
        if number <= 1:
            logger.info("前回記事なし: 第1話")
            return None, None

        prev_number = number - 1

        cached = posted_articles.get((title, prev_number))
        if cached is not None:
            prev_title, prev_url = cached
            logger.info("前回記事: series=%s number=%s source=run_cache url=%s", title, prev_number, prev_url)
            return prev_url, prev_title

        prev_url, prev_title = wp.find_post_by_title(format_article_title(title, prev_number))
        if prev_url is not None:
            logger.info("前回記事: series=%s number=%s source=wordpress url=%s", title, prev_number, prev_url)
            return prev_url, prev_title

        for legacy_title in _legacy_title_candidates(title, prev_number):
            prev_url, prev_title = wp.find_post_by_title(legacy_title)
            if prev_url is not None:
                logger.info(
                    "前回記事: series=%s number=%s source=wordpress(legacy) url=%s",
                    title, prev_number, prev_url,
                )
                return prev_url, prev_title

        logger.info("前回記事なし: series=%s number=%s", title, prev_number)
        return None, None


def create_application(config_path: str = "config/config.yaml") -> Application:
    """設定ファイルを読み込み Application インスタンスを返すファクトリ関数。"""
    manager = ConfigManager(config_path)
    config = manager.load()

    log_manager = LogManager(config.paths.log_file, level=config.log_level)
    log_manager.setup()

    return Application(config)
