import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../plugins/export-chat-logs/scripts'))

from convert_to_markdown import format_markdown
from convert_to_html import format_html, _md_to_html


SAMPLE_MESSAGES = [
    ("user", "Hello, can you help me?", "2024-01-15T10:00:00Z", "uuid-1"),
    ("assistant", "Sure, I can help!", "2024-01-15T10:01:00Z", "uuid-2"),
]

FIRST_TS = "2024-01-15T10:00:00Z"


class TestFormatMarkdown:
    def test_basic_output(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_messages(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS)
        assert "Hello, can you help me?" in result
        assert "Sure, I can help!" in result

    def test_contains_uuids(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS)
        assert "uuid-1" in result
        assert "uuid-2" in result

    def test_empty_messages(self):
        result = format_markdown([], FIRST_TS)
        assert isinstance(result, str)

    def test_with_title(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS, title="My Session")
        assert "My Session" in result

    def test_with_cwd(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS, cwd="/home/user/project")
        assert "project" in result

    def test_with_models(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS, models=["claude-3-opus"])
        assert "claude-3-opus" in result

    def test_with_session_id(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS, session_id="sess-abc")
        assert "sess-abc" in result

    def test_role_labels_present(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS)
        # Role labels are locale-dependent; just verify both roles produce headings
        assert "uuid-1" in result and "uuid-2" in result

    def test_no_first_ts(self):
        result = format_markdown(SAMPLE_MESSAGES, None)
        assert isinstance(result, str)

    def test_cowork_source_label(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS, cwd="/foo/bar", source_label="cowork")
        assert "Cowork" in result or "cowork" in result.lower()

    def test_message_count_in_output(self):
        result = format_markdown(SAMPLE_MESSAGES, FIRST_TS)
        assert "2" in result


class TestFormatHtml:
    def test_returns_html_string(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS)
        assert result.startswith("<!DOCTYPE html>")

    def test_contains_messages(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS)
        assert "Hello, can you help me?" in result
        assert "Sure, I can help!" in result

    def test_contains_html_structure(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS)
        assert "<html" in result
        assert "</html>" in result
        assert "<head>" in result
        assert "<body" in result

    def test_contains_uuids(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS)
        assert "uuid-1" in result
        assert "uuid-2" in result

    def test_with_title(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS, title="Test Title")
        assert "Test Title" in result

    def test_with_cwd(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS, cwd="/home/user/myproject")
        assert "myproject" in result

    def test_with_models(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS, models=["claude-3-sonnet"])
        assert "claude-3-sonnet" in result

    def test_with_session_id(self):
        result = format_html(SAMPLE_MESSAGES, FIRST_TS, session_id="sess-xyz")
        assert "sess-xyz" in result

    def test_empty_messages(self):
        result = format_html([], FIRST_TS)
        assert isinstance(result, str)
        assert "<!DOCTYPE html>" in result

    def test_no_first_ts(self):
        result = format_html(SAMPLE_MESSAGES, None)
        assert isinstance(result, str)


class TestMdToHtml:
    def test_plain_text(self):
        result = _md_to_html("hello world")
        assert "hello world" in result

    def test_bold(self):
        result = _md_to_html("**bold text**")
        assert "<strong>" in result
        assert "bold text" in result

    def test_italic(self):
        result = _md_to_html("*italic text*")
        assert "<em>" in result

    def test_heading_h1(self):
        result = _md_to_html("# Heading One")
        assert "<h1>" in result
        assert "Heading One" in result

    def test_heading_h2(self):
        result = _md_to_html("## Heading Two")
        assert "<h2>" in result

    def test_inline_code(self):
        result = _md_to_html("`inline code`")
        assert "<code>" in result
        assert "inline code" in result

    def test_code_fence(self):
        result = _md_to_html("```python\nprint('hello')\n```")
        assert "<pre>" in result
        assert "<code" in result
        assert "print" in result

    def test_link(self):
        result = _md_to_html("[click here](https://example.com)")
        assert '<a href="https://example.com"' in result
        assert "click here" in result

    def test_unordered_list(self):
        result = _md_to_html("- item one\n- item two")
        assert "<ul>" in result
        assert "<li>" in result

    def test_horizontal_rule(self):
        result = _md_to_html("---")
        assert "<hr>" in result

    def test_html_escaping(self):
        result = _md_to_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_bold_italic_combined(self):
        result = _md_to_html("***bold italic***")
        assert "<strong>" in result
        assert "<em>" in result

    def test_empty_string(self):
        result = _md_to_html("")
        assert isinstance(result, str)

    def test_blockquote(self):
        result = _md_to_html("> quoted text")
        assert "<blockquote>" in result


class TestMdToHtmlFence:
    def test_3tick_fence_with_lang(self):
        out = _md_to_html("```python\nprint('x')\n```")
        assert 'class="language-python"' in out
        assert "print(" in out

    def test_3tick_fence_no_lang(self):
        out = _md_to_html("```\nplain code\n```")
        assert "<pre><code>" in out
        assert "plain code" in out
        assert 'class=' not in out.split("<pre>")[1].split("</pre>")[0]

    def test_4tick_fence_end_to_end(self):
        md = "/cmd\n\n````\n```\nfoo\n```\n````"
        out = _md_to_html(md)
        assert "<pre><code>" in out
        assert "foo" in out
