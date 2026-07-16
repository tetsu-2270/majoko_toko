"""アプリケーション全体で共有するDataModelを定義するモジュール。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttachmentData:
    """メールから抽出した添付ファイル1件分のデータ。"""

    filename: str
    content: bytes
    content_type: str


@dataclass
class MailData:
    message_id: str
    subject: str
    title: str
    number: int | None
    category: str
    scheduled_at: str | None
    body: str
    attachments: list[AttachmentData] = field(default_factory=list)
    received_at_ms: int | None = None  # Gmail受信時刻(epochミリ秒、internalDate由来)。解決不可時はNone。
