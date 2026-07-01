def test_html_generator_inserts_content(sample_template):
    # TODO: HtmlGenerator実装後にテンプレート差し込みを検証
    assert "{{content}}" in sample_template
