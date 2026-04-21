from __future__ import annotations

from bob.tui.markdown_engine import MarkdownItEngine, MarkdownRenderStyle, StreamState, create_markdown_engine
from bob.tui.markdown_nodes import BlockQuote, BulletList, Document, Heading, Link, Paragraph


STYLE = MarkdownRenderStyle(
    reset="</>",
    dim="<dim>",
    bold="<bold>",
    underline="<u>",
    strike="<strike>",
    border="<border>",
    soft="<soft>",
    code="<code>",
    link="<link>",
    emphasis="<em>",
    strong="<strong>",
    heading1="<h1>",
    heading2="<h2>",
    heading3="<h3>",
)


def test_parse_builds_document_nodes() -> None:
    engine = MarkdownItEngine(STYLE)
    doc = engine.parse("# Title\n\n- item\n\n> quote\n")

    assert isinstance(doc, Document)
    assert isinstance(doc.children[0], Heading)
    assert isinstance(doc.children[1], BulletList)
    assert isinstance(doc.children[2], BlockQuote)


def test_windows_paths_with_underscores_render_literally() -> None:
    engine = MarkdownItEngine(STYLE)

    rendered = engine.render(r"Path: C:\repo\foo_bar\baz.py")

    assert rendered == r"Path: C:\repo\foo_bar\baz.py"


def test_inline_constructs_render_with_custom_styles() -> None:
    engine = MarkdownItEngine(STYLE)

    rendered = engine.render("Use `bob` and **ship it** plus *carefully*.")

    assert "Use <code>bob</>" in rendered
    assert "<strong>ship it</>" in rendered
    assert "<em>carefully</>" in rendered


def test_links_render_label_plus_url() -> None:
    engine = MarkdownItEngine(STYLE)
    doc = engine.parse("[OpenAI](https://platform.openai.com/docs)")

    paragraph = doc.children[0]
    assert isinstance(paragraph, Paragraph)
    assert isinstance(paragraph.children[0], Link)

    rendered = engine.render("[OpenAI](https://platform.openai.com/docs)")
    assert rendered == "<link>OpenAI</> (https://platform.openai.com/docs)"


def test_code_fence_renders_plain_colored_block() -> None:
    engine = MarkdownItEngine(STYLE)

    rendered = engine.render("```python\nprint('hi')\n```")

    assert rendered == "<dim>```python</>\n<code>print('hi')</>\n<dim>```</>"


def test_blockquote_and_list_render_compactly() -> None:
    engine = MarkdownItEngine(STYLE)

    rendered = engine.render("> note\n\n1. first\n2. second")

    assert rendered == (
        "<border>│</> note\n\n"
        "<dim>1.</> first\n\n"
        "<dim>2.</> second"
    )


def test_streaming_only_flushes_completed_lines() -> None:
    engine = MarkdownItEngine(STYLE)
    state = StreamState()

    first = engine.render_stream_chunk("Hello **wo", state)
    second = engine.render_stream_chunk("rld**\nNext", state)
    tail = engine.flush_stream_tail(state)

    assert first.rendered == ""
    assert first.pending == "Hello **wo"
    assert second.rendered == "Hello <strong>world</>\n"
    assert second.pending == "Next"
    assert tail == "Next"
    assert state.pending == ""


def test_streaming_plain_prose_flushes_by_words() -> None:
    engine = MarkdownItEngine(STYLE)
    state = StreamState()

    first = engine.render_stream_chunk("Hello there fr", state)
    second = engine.render_stream_chunk("iend", state)
    third = engine.render_stream_chunk(" now", state)

    assert first.rendered == "Hello there "
    assert first.pending == "fr"
    assert second.rendered == ""
    assert second.pending == "friend"
    assert third.rendered == "friend "
    assert third.pending == "now"


def test_streaming_markdown_rich_line_waits_for_completion() -> None:
    engine = MarkdownItEngine(STYLE)
    state = StreamState()

    first = engine.render_stream_chunk("Use **bo", state)
    second = engine.render_stream_chunk("ld** text", state)
    tail = engine.flush_stream_tail(state)

    assert first.rendered == ""
    assert second.rendered == ""
    assert tail == "Use <strong>bold</> text"


def test_streaming_preserves_blank_lines() -> None:
    engine = MarkdownItEngine(STYLE)
    state = StreamState()

    chunk = engine.render_stream_chunk("One\n\nTwo\n", state)

    assert chunk.rendered == "One\n\nTwo\n"
    assert chunk.pending == ""


def test_factory_supports_legacy_fallback() -> None:
    engine = create_markdown_engine("legacy", STYLE)
    rendered = engine.render("`code`")

    assert rendered == "<code>code</>"
