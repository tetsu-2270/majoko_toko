"""アプリケーション全体で共有するDataModelを定義するモジュール。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MailData:
    message_id: str
    subject: str
    title: str
    number: int | None
    category: str
    scheduled_at: str | None
    body: str
    attachment_paths: list[Path] = field(default_factory=list)
