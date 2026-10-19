from library.text.markdown import markdown_text


def test_markdown_converts_headings_links_and_code():
    html = "<h1>Title</h1><p>Read <a href='https://example.com'>this</a> and <code>x + 1</code>.</p>"

    assert markdown_text(html) == "# Title\n\nRead [this](https://example.com) and `x + 1`.\n"


def test_markdown_converts_fenced_code():
    html = "<pre><code>print('hello')\n</code></pre>"

    assert markdown_text(html) == "```\nprint('hello')\n```\n"
