from pathlib import Path

from src.image_sorter import ImageSorter


def _paths(names: list[str]) -> list[Path]:
    return [Path(n) for n in names]


def test_image_sorter_handles_rollover(sample_image_names: list[str]) -> None:
    sorter = ImageSorter()
    result = sorter.sort(_paths(sample_image_names))
    assert [p.name for p in result] == [
        "IMG9998.jpg",
        "IMG9999.jpg",
        "IMG0001.jpg",
        "IMG0002.jpg",
    ]


def test_image_sorter_no_rollover() -> None:
    sorter = ImageSorter()
    paths = _paths(["IMG0003.jpg", "IMG0001.jpg", "IMG0002.jpg"])
    result = sorter.sort(paths)
    assert [p.name for p in result] == ["IMG0001.jpg", "IMG0002.jpg", "IMG0003.jpg"]


def test_image_sorter_single_image() -> None:
    sorter = ImageSorter()
    result = sorter.sort(_paths(["IMG0001.jpg"]))
    assert len(result) == 1


def test_image_sorter_empty() -> None:
    sorter = ImageSorter()
    assert sorter.sort([]) == []


def test_image_sorter_rollover_boundary() -> None:
    """ロールオーバー境界付近（9999→0001のみ）でも正しく動作する。"""
    sorter = ImageSorter()
    paths = _paths(["IMG0001.jpg", "IMG9999.jpg"])
    result = sorter.sort(paths)
    assert [p.name for p in result] == ["IMG9999.jpg", "IMG0001.jpg"]
