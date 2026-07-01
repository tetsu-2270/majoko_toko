import logging
from pathlib import Path

from src.log_manager import LogManager


def test_log_manager_creates_log_file(temp_project_dir: Path) -> None:
    log_file = temp_project_dir / "logs" / "application.log"
    manager = LogManager(log_file, level="DEBUG")
    manager.setup()

    logger = LogManager.get_logger("test")
    logger.info("テストログ")

    assert log_file.exists()
    assert "テストログ" in log_file.read_text(encoding="utf-8")


def test_log_manager_respects_level(temp_project_dir: Path) -> None:
    log_file = temp_project_dir / "logs" / "warn.log"
    manager = LogManager(log_file, level="WARNING")
    manager.setup()

    logger = LogManager.get_logger("level_test")
    logger.debug("デバッグ")
    logger.warning("警告")

    content = log_file.read_text(encoding="utf-8")
    assert "デバッグ" not in content
    assert "警告" in content
