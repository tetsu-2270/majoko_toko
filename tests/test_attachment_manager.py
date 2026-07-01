import email
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from src.attachment_manager import AttachmentManager


def _make_msg_with_attachments(filenames: list[str]) -> email.message.Message:
    msg = MIMEMultipart()
    msg.attach(MIMEText("カテゴリー：Blog", "plain"))
    for fname in filenames:
        img = MIMEImage(b"\xff\xd8\xff" + b"\x00" * 10, _subtype="jpeg")
        img.add_header("Content-Disposition", "attachment", filename=fname)
        msg.attach(img)
    return msg


def test_attachment_manager_saves_files(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)
    msg = _make_msg_with_attachments(["IMG0001.jpg", "IMG0002.jpg"])

    saved = manager.save(msg)

    assert len(saved) == 2
    for path in saved:
        assert path.exists()


def test_attachment_manager_filters_non_image(temp_project_dir: Path) -> None:
    save_dir = temp_project_dir / "images"
    manager = AttachmentManager(save_dir)

    msg = MIMEMultipart()
    text_part = MIMEText("dummy")
    text_part.add_header("Content-Disposition", "attachment", filename="note.txt")
    msg.attach(text_part)

    saved = manager.save(msg)
    assert saved == []


def test_attachment_manager_creates_dir(tmp_path: Path) -> None:
    save_dir = tmp_path / "new_dir" / "images"
    manager = AttachmentManager(save_dir)
    manager.save(_make_msg_with_attachments(["IMG0001.png"]))
    assert save_dir.exists()
