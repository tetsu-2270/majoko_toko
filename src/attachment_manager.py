"""メールから添付画像を取り出して保存するモジュール。"""

from __future__ import annotations

import logging
from email.message import Message
from pathlib import Path

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class AttachmentManager:
    """添付ファイルを指定ディレクトリへ保存する。"""

    def __init__(self, save_dir: str | Path) -> None:
        self._save_dir = Path(save_dir)

    def save(self, msg: Message) -> list[Path]:
        """メッセージから画像添付ファイルを抽出・保存し、保存パスのリストを返す。

        対応拡張子: .jpg / .jpeg / .png
        ファイル名は添付ファイルのオリジナル名を使用する。
        """
        self._save_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            if not filename:
                continue

            suffix = Path(filename).suffix.lower()
            if suffix not in _ALLOWED_EXTENSIONS:
                logger.debug("添付スキップ (対象外拡張子): %s", filename)
                continue

            data = part.get_payload(decode=True)
            if not data:
                continue

            dest = self._save_dir / filename
            dest.write_bytes(data)
            saved.append(dest)
            logger.info("添付保存: %s", dest)

        return saved
