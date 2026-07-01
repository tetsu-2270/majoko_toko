def test_history_manager_writes_json(temp_project_dir):
    # TODO: HistoryManager実装後にJSON保存を検証
    assert (temp_project_dir / "history").exists()
