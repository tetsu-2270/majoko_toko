from pathlib import Path

from src.history_manager import HistoryManager, PostHistory


def _make_history(post_id: int = 1, message_id: str = "msg-001") -> PostHistory:
    return PostHistory(
        post_id=post_id,
        title="テスト記事",
        category="Blog",
        created_at="2026-07-02T00:00:00+09:00",
        mail_message_id=message_id,
    )


def test_history_manager_writes_json(temp_project_dir: Path) -> None:
    history_file = temp_project_dir / "history" / "post_history.json"
    manager = HistoryManager(history_file)
    manager.save(_make_history())

    assert history_file.exists()


def test_history_manager_stores_and_retrieves(temp_project_dir: Path) -> None:
    history_file = temp_project_dir / "history" / "post_history.json"
    manager = HistoryManager(history_file)
    h = _make_history(post_id=42, message_id="msg-042")
    manager.save(h)

    found = manager.find_by_message_id("msg-042")
    assert found is not None
    assert found.post_id == 42
    assert found.title == "テスト記事"


def test_history_manager_returns_none_for_unknown(temp_project_dir: Path) -> None:
    history_file = temp_project_dir / "history" / "post_history.json"
    manager = HistoryManager(history_file)

    assert manager.find_by_message_id("no-such-id") is None


def test_history_manager_appends_multiple(temp_project_dir: Path) -> None:
    history_file = temp_project_dir / "history" / "post_history.json"
    manager = HistoryManager(history_file)
    manager.save(_make_history(post_id=1, message_id="msg-001"))
    manager.save(_make_history(post_id=2, message_id="msg-002"))

    all_records = manager.all()
    assert len(all_records) == 2
    assert all_records[1].post_id == 2
