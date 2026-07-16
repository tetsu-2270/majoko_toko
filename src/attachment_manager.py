"""メールから添付画像を取り出して保存するモジュール。"""

from __future__ import annotations

import logging
from pathlib import Path

from src.models import AttachmentData

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class AttachmentManager:
    """添付ファイルを指定ディレクトリへ保存する。"""

    def __init__(self, save_dir: str | Path) -> None:
        self._save_dir = Path(save_dir)

    def save(self, attachments: list[AttachmentData]) -> list[Path]:
        """添付データを画像として保存し、保存順のパスリストを返す。

        対応拡張子: .jpg / .jpeg / .png（大文字・小文字を区別しない）
        ファイル名は添付ファイルのオリジナル名を使用するが、
        ディレクトリトラバーサル対策としてbasenameのみを使用する。
        """
        self._save_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []

        for attachment in attachments:
            filename = Path(attachment.filename).name
            if not filename:
                continue

            suffix = Path(filename).suffix.lower()
            if suffix not in _ALLOWED_EXTENSIONS:
                logger.debug("添付スキップ (対象外拡張子): %s", filename)
                continue

            if not attachment.content:
                continue

            dest = self._save_dir / filename
            dest.write_bytes(attachment.content)
            saved.append(dest)
            logger.info("添付保存: %s", dest)

        return saved
