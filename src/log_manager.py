"""アプリケーションのログ出力を一元管理するモジュール。"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


class LogManager:
    """ファイルとコンソールへのログ出力を設定する。"""

    def __init__(self, log_file: str | Path, level: str = "INFO") -> None:
        self._log_file = Path(log_file)
        self._level = getattr(logging, level.upper(), logging.INFO)

    def setup(self) -> None:
        """ルートロガーにハンドラを設定する。重複設定を防ぐため既存ハンドラはクリアする。"""
        self._log_file.parent.mkdir(parents=True, exist_ok=True)

        root = logging.getLogger()
        root.setLevel(self._level)
        root.handlers.clear()

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        file_handler = logging.handlers.RotatingFileHandler(
            self._log_file,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """指定名のロガーを返す。"""
        return logging.getLogger(name)
