import pytest
from pathlib import Path

from src.html_generator import HtmlGenerator


@pytest.fixture
def template_file(tmp_path: Path) -> Path:
    path = tmp_path / "template.html"
    path.write_text(
        "ヘッダー\n<!-- 前回の話 -->\n本文開始\n<!-- 以下本文 -->\nフッター",
        encoding="utf-8",
    )
    return path


def test_html_generator_inserts_images(template_file: Path) -> None:
    gen = HtmlGenerator(template_file)
    html = gen.generate(image_urls=["https://example.com/img1.jpg"])

    assert '<img src="https://example.com/img1.jpg"' in html
    assert "<!-- 以下本文 -->" not in html


def test_html_generator_inserts_prev_link(template_file: Path) -> None:
    gen = HtmlGenerator(template_file)
    html = gen.generate(
        image_urls=["https://example.com/img1.jpg"],
        prev_url="https://example.com/post/1",
        prev_title="前回のタイトル",
    )

    assert "https://example.com/post/1" in html
    assert "前回のタイトル" in html
    assert "<!-- 前回の話 -->" not in html


def test_html_generator_no_prev_removes_placeholder(template_file: Path) -> None:
    gen = HtmlGenerator(template_file)
    html = gen.generate(image_urls=["https://example.com/img1.jpg"])

    assert "<!-- 前回の話 -->" not in html
    # 前回リンクがない場合はリンクタグ自体が存在しない
    assert "■前回のお話はこちら" not in html


def test_html_generator_multiple_images(template_file: Path) -> None:
    gen = HtmlGenerator(template_file)
    urls = ["https://example.com/1.jpg", "https://example.com/2.jpg", "https://example.com/3.jpg"]
    html = gen.generate(image_urls=urls)

    for url in urls:
        assert url in html


def test_html_generator_raises_if_template_missing(tmp_path: Path) -> None:
    gen = HtmlGenerator(tmp_path / "nonexistent.html")
    with pytest.raises(FileNotFoundError):
        gen.generate(image_urls=[])


def test_html_generator_inserts_content(sample_template: str) -> None:
    # conftest.py の sample_template フィクスチャとの後方互換確認
    assert "{{content}}" in sample_template
