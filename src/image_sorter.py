"""添付画像をIMGファイル名のロールオーバーを考慮して並び替えるモジュール。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_IMG_NUMBER_RE = re.compile(r"(\d+)", re.IGNORECASE)

# この差を超えたらロールオーバー（9999→0001 等）が発生したと判定する
_ROLLOVER_THRESHOLD = 5000


def _extract_number(path: Path) -> int:
    """ファイル名から末尾の数値を抽出する。数値がなければ -1 を返す。"""
    numbers = _IMG_NUMBER_RE.findall(path.stem)
    return int(numbers[-1]) if numbers else -1


class ImageSorter:
    """IMG9999→IMG0001 のロールオーバーを考慮した昇順ソートを行う。

    ロールオーバー検知: 数値昇順で並べたとき、隣接する値の差が
    _ROLLOVER_THRESHOLD を超える箇所でリストを分割し、
    大きい番号群 → 小さい番号群 の順に再結合する。
    """

    def sort(self, image_paths: list[Path]) -> list[Path]:
        """画像パスのリストをロールオーバー考慮で並び替えて返す。"""
        if not image_paths:
            return []

        # ファイル名数値で昇順ソート
        sorted_paths = sorted(image_paths, key=_extract_number)
        numbers = [_extract_number(p) for p in sorted_paths]

        # 隣接差が閾値を超える箇所を探す（ロールオーバー境界）
        split_index: int | None = None
        for i in range(len(numbers) - 1):
            if numbers[i + 1] - numbers[i] > _ROLLOVER_THRESHOLD:
                split_index = i + 1
                break

        if split_index is None:
            # ロールオーバーなし
            logger.debug("ロールオーバーなし: %s枚をそのまま並び替え", len(sorted_paths))
            return sorted_paths

        # 昇順ソート後: [小さい番号群 ... | split_index ... 大きい番号群]
        # ロールオーバーが起きていた場合、大きい番号が先に撮影されているため
        # 大きい番号群 → 小さい番号群 の順に並べ替える
        low_nums = sorted_paths[:split_index]   # 0001, 0002 ... (ロールオーバー後)
        high_nums = sorted_paths[split_index:]  # 9998, 9999 ... (ロールオーバー前)
        result = high_nums + low_nums
        logger.info(
            "ロールオーバー検知: %s(%d枚) → %s(%d枚)",
            high_nums[0].name,
            len(high_nums),
            low_nums[0].name,
            len(low_nums),
        )
        return result
