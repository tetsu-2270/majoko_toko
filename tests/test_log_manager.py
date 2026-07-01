def test_log_manager_creates_log_dir(temp_project_dir):
    # TODO: LogManager実装後にログ出力を検証
    assert (temp_project_dir / "logs").exists()
