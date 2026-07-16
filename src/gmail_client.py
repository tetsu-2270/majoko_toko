"""Gmail API (OAuth 2.0) 経由で未読メールを取得するモジュール。"""

from __future__ import annotations

import base64
import email
import logging
import re
from datetime import timezone
from email.header import decode_header as _decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config_manager import GmailConfig
from src.models import AttachmentData, MailData

logger = logging.getLogger(__name__)

_SPACE = r"[ 　]"
_TILDE = r"[~～〜]"
_DIGIT = r"[0-9０-９]"
_N = r"[NnＮｎ]"
_O = r"[OoＯｏ]"

# 解析順序: (1)~・〜・～区切り → (2)半角/全角No形式 → (3)区切りなしの裸の数字。
# "AAAA No 42"のような文字列は、(3)を先に試すと"No"まで作品名に取り込まれてしまうため、
# 必ず(2)を(3)より先に判定する。
_TILDE_NUMBER_RE = re.compile(rf"^(.+?){_SPACE}+{_TILDE}{_SPACE}*({_DIGIT}+){_SPACE}*$")
_NO_NUMBER_RE = re.compile(rf"^(.+?){_SPACE}+{_N}{_O}{_SPACE}*({_DIGIT}+){_SPACE}*$")
_BARE_NUMBER_RE = re.compile(rf"^(.+?){_SPACE}+({_DIGIT}+){_SPACE}*$")
_NUMBER_PATTERNS = (_TILDE_NUMBER_RE, _NO_NUMBER_RE, _BARE_NUMBER_RE)
_TRAILING_SEPARATOR_ONLY_RE = re.compile(rf"(?:{_TILDE}|{_N}{_O}){_SPACE}*$")
_FULLWIDTH_DIGIT_TRANS = str.maketrans("０１２３４５６７８９", "0123456789")
_CATEGORY_RE = re.compile(r"^カテゴリ[ーー]?[：:]\s*(.+)", re.MULTILINE)
_SCHEDULED_RE = re.compile(r"^投稿日[：:]\s*(.+)", re.MULTILINE)


def _decode_str(value: str) -> str:
    """MIME エンコードされたヘッダ文字列をデコードする。"""
    parts = _decode_header(value)
    result = ""
    for part, charset in parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="replace")
        else:
            result += part
    return result


def parse_subject(subject: str) -> tuple[str, int | None]:
    """件名を解析して作品名と話数を返す。

    話数の表記揺れ（半角/全角スペース、半角チルダ"~"/全角チルダ"～"/波ダッシュ"〜"、
    半角/全角"No"表記、半角/全角数字の組み合わせ）を吸収し、話数を数値として取り出す。
    判定は次の優先順で行う（"AAAA No 42"のような"No"区切りが、区切りなしの裸の数字
    パターンに"No"ごと作品名として取り込まれるのを防ぐため）。

        1. "~"・"〜"・"～"区切りの明示話数
        2. 半角/全角"No"形式の明示話数
        3. 区切りなし（空白のみ）の裸の数字

    話数を認識できない件名は、件名全体を作品名として扱い話数`None`を返す（呼び出し側で
    WordPress上の同一作品名の最新話数+1を自動採番する）。

    例:
        "AAAA 42"        → ("AAAA", 42)
        "AAAA　４２"      → ("AAAA", 42)
        "AAAA ~ 42"      → ("AAAA", 42)
        "AAAA　〜　４２"  → ("AAAA", 42)
        "AAAA No42"      → ("AAAA", 42)
        "AAAA No 42"     → ("AAAA", 42)
        "AAAA Ｎｏ４２"   → ("AAAA", 42)
        "AAAA"           → ("AAAA", None)

    Raises:
        ValueError: 件名が空の場合、または"AAAA ~"・"AAAA No"のように区切り文字（表記）
            だけが末尾に残り話数が存在しない場合。
    """
    if not subject:
        raise ValueError("件名が空です")

    for pattern in _NUMBER_PATTERNS:
        m = pattern.match(subject)
        if m:
            title, digits = m.group(1), m.group(2)
            return title, int(digits.translate(_FULLWIDTH_DIGIT_TRANS))

    if _TRAILING_SEPARATOR_ONLY_RE.search(subject):
        raise ValueError(f"件名の話数が区切り文字のみで空です: {subject!r}")

    return subject, None


def parse_body(body: str) -> tuple[str, str | None]:
    """本文を解析してカテゴリと投稿日を返す。

    Returns:
        (category, scheduled_at) のタプル。category は必須。
    Raises:
        ValueError: カテゴリが見つからない場合。
    """
    cm = _CATEGORY_RE.search(body)
    if not cm:
        raise ValueError(f"本文にカテゴリが見つかりません: {body!r}")
    category = cm.group(1).strip()

    sm = _SCHEDULED_RE.search(body)
    scheduled_at = sm.group(1).strip() if sm else None

    return category, scheduled_at


class GmailClient:
    """Gmail API (OAuth 2.0, gmail.readonlyスコープ) で未読メールを取得するクライアント。

    gmail.readonlyスコープでは既読化・ラベル付与はできないため、
    処理済みメールの重複判定はHistoryManager（投稿履歴）側で行う。
    """

    def __init__(self, config: GmailConfig) -> None:
        self._config = config
        self._service = None

    def connect(self) -> None:
        """OAuth 2.0 認証を行い Gmail API クライアントを構築する。

        token.jsonが存在し有効であればそれを利用する。
        存在しない、または失効している場合はローカルブラウザでの認証フローを実行し、
        認証後の情報をtoken.jsonへ保存する。
        """
        logger.info("Gmail に接続します: %s", self._config.target_address)
        creds = self._load_credentials()
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        logger.info("Gmail 接続成功")

    def disconnect(self) -> None:
        """クライアントを解放する。"""
        self._service = None

    def fetch_unread(self) -> list[MailData]:
        """未読メールを取得して MailData のリストを返す。"""
        self._assert_connected()

        mail_list: list[MailData] = []
        response = (
            self._service.users()  # type: ignore[union-attr]
            .messages()
            .list(userId="me", q="is:unread")
            .execute()
        )

        for item in response.get("messages", []):
            raw_msg = (
                self._service.users()  # type: ignore[union-attr]
                .messages()
                .get(userId="me", id=item["id"], format="raw")
                .execute()
            )
            msg = self._decode_raw_message(raw_msg["raw"])

            try:
                mail_data = self._parse_message(msg, raw_msg)
                mail_list.append(mail_data)
                logger.info("メール取得: %s", mail_data.subject)
            except (ValueError, KeyError) as exc:
                logger.warning("メール解析スキップ: %s", exc)

        return mail_list

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _load_credentials(self) -> Credentials:
        """token_path から認証情報を読み込む。無効・不在の場合は初回OAuthフローを実行する。"""
        token_path = Path(self._config.token_path)
        creds: Credentials | None = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self._config.scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._config.credentials_path, self._config.scopes
                )
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    @staticmethod
    def _decode_raw_message(raw: str) -> Message:
        """Gmail APIのbase64url raw文字列をemail.message.Messageへ変換する。"""
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        return email.message_from_bytes(decoded)

    def _assert_connected(self) -> None:
        if self._service is None:
            raise RuntimeError("connect() を先に呼び出してください。")

    def _parse_message(self, msg: Message, raw_msg: dict) -> MailData:
        """email.Message を MailData に変換する。

        件名はMIMEデコード後、前後の空白のみを除去した文字列を`MailData.subject`として保持する。
        `parse_subject()`が作品名・話数（表記揺れ吸収済み）を解析し、話数が無ければ
        `MailData.number`は`None`となる（Application側でWordPress検索により自動採番する）。
        件名が空、または区切り文字のみで話数が存在しない場合は`parse_subject()`が
        `ValueError`を送出し、呼び出し元（`fetch_unread`）がこのメールをスキップして
        WARNログへ記録する。

        `raw_msg["internalDate"]`（Gmail APIが返すepochミリ秒文字列）をGmail受信時刻の
        正本として`MailData.received_at_ms`へ設定する。複数メール処理時の投稿順の
        判定に使用する（順序解決はApplication側の責務）。
        """
        raw_subject = msg.get("Subject", "")
        subject = _decode_str(raw_subject).strip()
        message_id = msg.get("Message-ID", "") or raw_msg.get("id", "")

        body = self._extract_body(msg)
        title, number = parse_subject(subject)
        category, scheduled_at = parse_body(body)
        attachments = self._extract_attachments(msg)
        received_at_ms = self._resolve_received_at_ms(raw_msg, msg, subject)

        return MailData(
            message_id=message_id,
            subject=subject,
            title=title,
            number=number,
            category=category,
            scheduled_at=scheduled_at,
            body=body,
            attachments=attachments,
            received_at_ms=received_at_ms,
        )

    @staticmethod
    def _resolve_received_at_ms(raw_msg: dict, msg: Message, subject: str) -> int | None:
        """Gmail受信時刻をepochミリ秒で解決する。

        `raw_msg["internalDate"]`を優先し、欠落・不正な場合のみメールの`Date`ヘッダーへ
        フォールバックする。どちらも得られない場合は`None`を返しWARNログを記録する
        （アプリ全体は停止しない。並び替え時は時刻不明メールとして扱われる）。
        """
        internal_date = raw_msg.get("internalDate")
        if internal_date:
            try:
                return int(internal_date)
            except (TypeError, ValueError):
                logger.warning("internalDateの解析に失敗しました (件名: %s): %r", subject, internal_date)

        date_header = msg.get("Date")
        if date_header:
            try:
                dt = parsedate_to_datetime(date_header)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except (TypeError, ValueError, OverflowError):
                logger.warning("Dateヘッダーの解析に失敗しました (件名: %s): %r", subject, date_header)

        logger.warning("受信時刻を解決できませんでした (件名: %s)", subject)
        return None

    @staticmethod
    def _extract_attachments(msg: Message) -> list[AttachmentData]:
        """MIMEパートを再帰的に走査し、ファイル名を持つ添付を抽出する。"""
        attachments: list[AttachmentData] = []

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue

            raw_filename = part.get_filename()
            if not raw_filename:
                continue

            filename = _decode_str(raw_filename)
            data = part.get_payload(decode=True)
            if not data:
                continue

            attachments.append(
                AttachmentData(
                    filename=filename,
                    content=data,
                    content_type=part.get_content_type(),
                )
            )

        return attachments

    @staticmethod
    def _extract_body(msg: Message) -> str:
        """メール本文（text/plain）を取得する。"""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")  # type: ignore[union-attr]
            return ""
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        return str(payload or "")
