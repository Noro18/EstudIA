from apps.qa.views import render_markdown


def test_render_markdown_formats_text_and_escapes_html():
    rendered = render_markdown("**Tetum**\n\n<script>alert('x')</script>")

    assert "<strong>Tetum</strong>" in rendered
    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered
