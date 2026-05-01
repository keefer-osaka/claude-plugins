import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../plugins/export-chat-logs/scripts'))

import json
import tempfile
from datetime import datetime, timezone, timedelta
from common import (
    parse_ts, format_local_ts, safe_format_ts, compute_active_duration,
    clean_string_content, extract_text_blocks, parse_session,
    is_trivial_stats, is_skill_only_session, make_output_path,
    resolve_display_title, TZ_LOCAL, TZ_LABEL,
)


class TestParseTs:
    def test_utc_z(self):
        dt = parse_ts("2024-01-15T10:30:00Z")
        assert dt.tzinfo is not None
        assert dt.year == 2024

    def test_iso_with_offset(self):
        dt = parse_ts("2024-01-15T10:30:00+00:00")
        assert dt.tzinfo is not None

    def test_returns_datetime(self):
        result = parse_ts("2024-06-01T00:00:00Z")
        assert isinstance(result, datetime)


class TestSafeFormatTs:
    def test_valid_ts(self):
        result = safe_format_ts("2024-01-15T10:30:00Z")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_invalid_ts_returns_original(self):
        result = safe_format_ts("not-a-timestamp")
        assert result == "not-a-timestamp"

    def test_invalid_ts_with_fallback(self):
        result = safe_format_ts("bad", fallback="N/A")
        assert result == "N/A"


class TestComputeActiveDuration:
    def test_empty(self):
        assert compute_active_duration([]) == 0

    def test_single(self):
        assert compute_active_duration(["2024-01-01T00:00:00Z"]) == 0

    def test_consecutive_within_30min(self):
        ts1 = "2024-01-01T00:00:00Z"
        ts2 = "2024-01-01T00:10:00Z"
        result = compute_active_duration([ts1, ts2])
        assert abs(result - 600) < 1

    def test_gap_over_30min_excluded(self):
        ts1 = "2024-01-01T00:00:00Z"
        ts2 = "2024-01-01T01:00:00Z"
        result = compute_active_duration([ts1, ts2])
        assert result == 0


class TestCleanStringContent:
    def test_plain_text(self):
        assert clean_string_content("hello world") == "hello world"

    def test_strips_control_chars(self):
        result = clean_string_content("hello\x00world")
        assert "\x00" not in result

    def test_local_command_stdout(self):
        assert clean_string_content("<local-command-stdout>foo</local-command-stdout>") == ""

    def test_command_message_tag(self):
        result = clean_string_content("<command-message>test</command-message>")
        assert result == "/test"

    def test_command_name_tag(self):
        result = clean_string_content("<command-name>myskill</command-name>")
        assert result == "myskill"

    def test_empty_string(self):
        assert clean_string_content("") == ""

    def test_command_with_backtick_in_args(self):
        text = (
            "<command-name>cmd</command-name>"
            "<command-message>cmd</command-message>"
            "<command-args>```\nfoo\n```</command-args>"
        )
        out = clean_string_content(text)
        assert out == "/cmd\n\n````\n```\nfoo\n```\n````"

    def test_command_with_4tick_in_args(self):
        text = (
            "<command-name>cmd</command-name>"
            "<command-message>cmd</command-message>"
            "<command-args>````\nfoo\n````</command-args>"
        )
        out = clean_string_content(text)
        assert out == "/cmd\n\n`````\n````\nfoo\n````\n`````"

    def test_command_with_plain_args(self):
        text = (
            "<command-name>debug</command-name>"
            "<command-message>debug</command-message>"
            "<command-args>some args here</command-args>"
        )
        out = clean_string_content(text)
        assert out == "/debug\n\n```\nsome args here\n```"

    def test_command_without_args_unchanged(self):
        text = (
            "<command-name>cmd</command-name>"
            "<command-message>cmd</command-message>"
        )
        out = clean_string_content(text)
        assert out == "/cmd"


class TestExtractTextBlocks:
    def test_string_input(self):
        assert extract_text_blocks("hello") == "hello"

    def test_list_with_text_block(self):
        content = [{"type": "text", "text": "hello"}]
        assert extract_text_blocks(content) == "hello"

    def test_list_filters_non_text(self):
        content = [
            {"type": "tool_use", "name": "Bash"},
            {"type": "text", "text": "response"},
        ]
        assert extract_text_blocks(content) == "response"

    def test_empty_list(self):
        assert extract_text_blocks([]) == ""

    def test_non_list_non_str(self):
        assert extract_text_blocks(None) == ""

    def test_multiple_text_blocks(self):
        content = [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]
        result = extract_text_blocks(content)
        assert "first" in result
        assert "second" in result


class TestIsTrivialStats:
    def test_zero_tokens_is_trivial(self):
        assert is_trivial_stats(0, 0, None) is True

    def test_enough_output_tokens_not_trivial(self):
        assert is_trivial_stats(100, 200, None) is False

    def test_low_tokens_short_duration_trivial(self):
        assert is_trivial_stats(10, 50, 30) is True

    def test_low_tokens_long_duration_not_trivial(self):
        assert is_trivial_stats(10, 50, 120) is False

    def test_low_tokens_none_duration_trivial(self):
        assert is_trivial_stats(10, 50, None) is True


class TestIsSkillOnlySession:
    def test_empty_messages(self):
        assert is_skill_only_session([]) is True

    def test_skill_command_only(self):
        msgs = [("user", "/myskill", "ts", "id")]
        assert is_skill_only_session(msgs) is True

    def test_meta_command_only(self):
        msgs = [("user", "/help", "ts", "id")]
        assert is_skill_only_session(msgs) is True

    def test_real_message_not_skill_only(self):
        msgs = [("user", "hello please help", "ts", "id")]
        assert is_skill_only_session(msgs) is False

    def test_ask_user_question_tool_not_skill_only(self):
        msgs = [("user", "/myskill", "ts", "id")]
        assert is_skill_only_session(msgs, {"AskUserQuestion": 1}) is False


class TestResolveDisplayTitle:
    def test_with_title(self):
        title, source = resolve_display_title("My Title", "/foo/bar", None)
        assert title == "My Title"

    def test_fallback_to_preview(self):
        title, source = resolve_display_title("", "/foo/bar", None, "First message")
        assert title == "First message"

    def test_cowork_source_label(self):
        title, source = resolve_display_title("", "/foo/bar", "cowork")
        assert source is not None

    def test_no_title_no_preview_default(self):
        title, source = resolve_display_title("", "", None, "")
        assert title == "Claude Code"


class TestMakeOutputPath:
    def test_with_timestamp_and_title(self):
        path = make_output_path("/tmp/out", "2024-01-15T10:30:00Z", "My Session")
        assert path.startswith("/tmp/out/")
        assert "My_Session" in path
        assert path.endswith(".md")

    def test_with_no_title(self):
        path = make_output_path("/tmp/out", "2024-01-15T10:30:00Z", None)
        assert path.endswith(".md")

    def test_custom_extension(self):
        path = make_output_path("/tmp/out", "2024-01-15T10:30:00Z", "test", ext=".html")
        assert path.endswith(".html")

    def test_no_timestamp(self):
        path = make_output_path("/tmp/out", None, "title")
        assert "unknown" in path


class TestParseSession:
    def _make_jsonl(self, lines):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for line in lines:
            tmp.write(json.dumps(line) + "\n")
        tmp.close()
        return tmp.name

    def test_basic_session(self):
        lines = [
            {"sessionId": "abc123", "cwd": "/project", "timestamp": "2024-01-01T00:00:00Z",
             "message": {"role": "user", "content": "hello"}},
            {"timestamp": "2024-01-01T00:01:00Z",
             "message": {"role": "assistant", "content": "hi there",
                         "usage": {"input_tokens": 10, "output_tokens": 5}}},
        ]
        path = self._make_jsonl(lines)
        result = parse_session(path)
        assert result["session_id"] == "abc123"
        assert result["cwd"] == "/project"
        assert len(result["messages"]) == 2
        os.unlink(path)

    def test_custom_title(self):
        lines = [
            {"type": "custom-title", "customTitle": "My Chat", "sessionId": "x",
             "message": {}},
            {"timestamp": "2024-01-01T00:00:00Z",
             "message": {"role": "user", "content": "test"}},
        ]
        path = self._make_jsonl(lines)
        result = parse_session(path)
        assert result["title"] == "My Chat"
        os.unlink(path)

    def test_empty_file(self):
        path = self._make_jsonl([])
        result = parse_session(path)
        assert result["messages"] == []
        assert result["title"] is None
        os.unlink(path)

    def test_token_accumulation(self):
        lines = [
            {"timestamp": "2024-01-01T00:00:00Z",
             "message": {"role": "assistant", "content": "resp",
                         "usage": {"input_tokens": 100, "output_tokens": 50,
                                   "cache_read_input_tokens": 20,
                                   "cache_creation_input_tokens": 10}}},
        ]
        path = self._make_jsonl(lines)
        result = parse_session(path)
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["cache_read"] == 20
        assert result["cache_creation"] == 10
        os.unlink(path)

    def test_tool_counts(self):
        lines = [
            {"timestamp": "2024-01-01T00:00:00Z",
             "message": {"role": "assistant",
                         "content": [{"type": "tool_use", "name": "Bash"},
                                     {"type": "tool_use", "name": "Bash"},
                                     {"type": "tool_use", "name": "Read"}]}},
        ]
        path = self._make_jsonl(lines)
        result = parse_session(path)
        assert result["tool_counts"].get("Bash") == 2
        assert result["tool_counts"].get("Read") == 1
        os.unlink(path)

    def test_compact_summary_filtered(self):
        lines = [
            {"message": {"role": "user", "content": "real question"},
             "timestamp": "2025-01-01T00:00:00Z", "uuid": "u1"},
            {"isCompactSummary": True,
             "message": {"role": "assistant", "content": "summary text",
                         "usage": {"input_tokens": 999, "output_tokens": 999}},
             "timestamp": "2025-01-01T00:00:01Z", "uuid": "compact"},
            {"message": {"role": "assistant", "content": "real answer",
                         "usage": {"input_tokens": 0, "output_tokens": 5}},
             "timestamp": "2025-01-01T00:00:02Z", "uuid": "u2"},
        ]
        path = self._make_jsonl(lines)
        result = parse_session(path)
        texts = [t for _role, t, *_ in result["messages"]]
        assert "summary text" not in texts
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 5
        os.unlink(path)
