from pathlib import Path

import pytest
import yaml

from src.config_manager import ConfigManager


def test_config_manager_loads_yaml(temp_project_dir: Path) -> None:
    config_path = temp_project_dir / "config" / "config.yaml"
    sample = Path("tests/sample_data/sample_config.yaml").read_text(encoding="utf-8")
    config_path.write_text(sample, encoding="utf-8")

    manager = ConfigManager(config_path)
    config = manager.load()

    assert config.gmail.target_address == "test@example.com"
    assert config.gmail.credentials_path == "config/credentials.json"
    assert config.gmail.token_path == "config/token.json"
    assert config.gmail.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert config.wordpress.url == "https://example.com"
    assert config.paths.log_file == "logs/application.log"
    assert config.retry.max_count == 3
    assert config.log_level == "INFO"


def test_config_manager_raises_if_file_missing(temp_project_dir: Path) -> None:
    manager = ConfigManager(temp_project_dir / "config" / "nonexistent.yaml")
    with pytest.raises(FileNotFoundError):
        manager.load()


def test_config_manager_raises_before_load(temp_project_dir: Path) -> None:
    manager = ConfigManager(temp_project_dir / "config" / "config.yaml")
    with pytest.raises(RuntimeError):
        _ = manager.config
