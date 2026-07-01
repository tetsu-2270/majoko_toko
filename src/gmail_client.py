"""Gmail API (OAuth 2.0) 経由で未読メールを取得するモジュール。"""

from __future__ import annotations

import base64
import email
import logging
import re
from email.header import decode_header as _decode_header
from email.message import Message
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config_manager import GmailConfig
from src.models import MailData

logger = logging.getLogger(__name__)

_SUBJECT_RE = re.compile(r"^(.+?)\s+No(\d+)\s*$", re.IGNORECASE)
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
    """件名を解析してタイトルと連番を返す。

    例:
        "魔女っこ日記 No5" → ("魔女っこ日記", 5)
        "新しい話"         → ("新しい話", None)
    """
    m = _SUBJECT_RE.match(subject.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return subject.strip(), None


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
                mail_data = self._parse_message(msg)
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

    def _parse_message(self, msg: Message) -> MailData:
        """email.Message を MailData に変換する。"""
        raw_subject = msg.get("Subject", "")
        subject = _decode_str(raw_subject)
        message_id = msg.get("Message-ID", "")

        body = self._extract_body(msg)
        title, number = parse_subject(subject)
        category, scheduled_at = parse_body(body)

        return MailData(
            message_id=message_id,
            subject=subject,
            title=title,
            number=number,
            category=category,
            scheduled_at=scheduled_at,
            body=body,
        )

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
