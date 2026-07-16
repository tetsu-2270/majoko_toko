from pathlib import Path

from src.attachment_manager import AttachmentManager
from src.models import AttachmentData


def _jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * 10


def test_attachment_manager_saves_files(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [
        AttachmentData(filename="IMG0001.jpg", content=_jpeg_bytes(), content_type="image/jpeg"),
        AttachmentData(filename="IMG0002.jpg", content=_jpeg_bytes(), content_type="image/jpeg"),
    ]

    saved = manager.save(attachments)

    assert len(saved) == 2
    for path in saved:
        assert path.exists()


def test_attachment_manager_preserves_order(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [
        AttachmentData(filename="IMG0002.jpg", content=_jpeg_bytes(), content_type="image/jpeg"),
        AttachmentData(filename="IMG0001.jpg", content=_jpeg_bytes(), content_type="image/jpeg"),
    ]

    saved = manager.save(attachments)

    assert [p.name for p in saved] == ["IMG0002.jpg", "IMG0001.jpg"]


def test_attachment_manager_handles_uppercase_extension(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [AttachmentData(filename="IMG0001.JPG", content=_jpeg_bytes(), content_type="image/jpeg")]

    saved = manager.save(attachments)

    assert len(saved) == 1
    assert saved[0].exists()


def test_attachment_manager_saves_png(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [AttachmentData(filename="IMG0001.PNG", content=b"\x89PNG\r\n", content_type="image/png")]

    saved = manager.save(attachments)

    assert len(saved) == 1


def test_attachment_manager_filters_non_image(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [AttachmentData(filename="note.txt", content=b"dummy", content_type="text/plain")]

    saved = manager.save(attachments)
    assert saved == []


def test_attachment_manager_creates_dir(tmp_path: Path) -> None:
    save_dir = tmp_path / "new_dir" / "images"
    manager = AttachmentManager(save_dir)
    manager.save([AttachmentData(filename="IMG0001.png", content=_jpeg_bytes(), content_type="image/png")])
    assert save_dir.exists()


def test_attachment_manager_skips_empty_content(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [AttachmentData(filename="IMG0001.jpg", content=b"", content_type="image/jpeg")]

    saved = manager.save(attachments)
    assert saved == []


def test_attachment_manager_rejects_path_traversal(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [
        AttachmentData(filename="../../etc/evil.jpg", content=_jpeg_bytes(), content_type="image/jpeg"),
    ]

    saved = manager.save(attachments)

    assert len(saved) == 1
    assert saved[0].parent == save_dir
    assert saved[0].name == "evil.jpg"


def test_attachment_manager_rejects_absolute_path(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    attachments = [
        AttachmentData(filename="/etc/evil.jpg", content=_jpeg_bytes(), content_type="image/jpeg"),
    ]

    saved = manager.save(attachments)

    assert len(saved) == 1
    assert saved[0].parent == save_dir
