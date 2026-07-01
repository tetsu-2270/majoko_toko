"""投稿履歴をJSONファイルで管理するモジュール。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PostHistory:
    post_id: int
    title: str
    category: str
    created_at: str
    mail_message_id: str


class HistoryManager:
    """post_history.json への投稿履歴の読み書きを担う。"""

    def __init__(self, history_file: str | Path) -> None:
        self._history_file = Path(history_file)

    def _load_all(self) -> list[dict]:
        if not self._history_file.exists():
            return []
        with self._history_file.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []

    def _save_all(self, records: list[dict]) -> None:
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        with self._history_file.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    def save(self, history: PostHistory) -> None:
        """投稿履歴を追記保存する。"""
        records = self._load_all()
        records.append(asdict(history))
        self._save_all(records)
        logger.info("投稿履歴を保存しました: post_id=%s", history.post_id)

    def find_by_message_id(self, mail_message_id: str) -> PostHistory | None:
        """Message-ID で履歴を検索する。見つからなければ None を返す。"""
        for record in self._load_all():
            if record.get("mail_message_id") == mail_message_id:
                return PostHistory(**record)
        return None

    def all(self) -> list[PostHistory]:
        """全履歴を返す。"""
        return [PostHistory(**r) for r in self._load_all()]
