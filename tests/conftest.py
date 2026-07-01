from pathlib import Path
import pytest


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "history").mkdir()
    (tmp_path / "temp").mkdir()
    (tmp_path / "images").mkdir()
    return tmp_path


@pytest.fixture
def sample_image_names() -> list[str]:
    return ["IMG9998.jpg", "IMG9999.jpg", "IMG0001.jpg", "IMG0002.jpg"]


@pytest.fixture
def sample_template() -> str:
    return "<html><body>{{content}}</body></html>"
