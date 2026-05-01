import sys
import os

_base = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/kb-ingest/scripts'))
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/_lib'))

import json
import pytest
import scan_sessions as ss


def _write_jsonl(path, lines):
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


# ── TestParseTs ────────────────────────────────────────────────────────────────

class TestParseTs:
    def test_utc_z_suffix(self):
        dt = ss.parse_ts("2026-01-01T00:00:00Z")
        assert dt.tzinfo is not None

    def test_plus_zero_offset(self):
        dt = ss.parse_ts("2026-01-01T12:30:00+00:00")
        assert dt.tzinfo is not None


# ── TestComputeActiveDuration ──────────────────────────────────────────────────

class TestComputeActiveDuration:
    def test_empty_list(self):
        assert ss.compute_active_duration([]) == 0

    def test_single_element(self):
        assert ss.compute_active_duration(["2026-01-01T00:00:00Z"]) == 0

    def test_two_within_30_min(self):
        result = ss.compute_active_duration([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:05:00Z",
        ])
        assert result == 300

    def test_gap_over_30_min_excluded(self):
        result = ss.compute_active_duration([
            "2026-01-01T00:00:00Z",
            "2026-01-01T01:00:00Z",  # 3600s gap > 1800s
        ])
        assert result == 0


# ── TestTruncate ───────────────────────────────────────────────────────────────

class TestTruncate:
    def test_under_max_len_unchanged(self):
        text = "hello"
        assert ss.truncate(text, max_len=100) == text

    def test_over_max_len_ends_with_truncation_message(self):
        text = "x" * 200
        result = ss.truncate(text, max_len=100)
        assert result.endswith("]")
        assert "截斷" in result
        assert len(result) > 100  # has the suffix appended


# ── TestCleanStringContent ─────────────────────────────────────────────────────

class TestCleanStringContent:
    def test_plain_text_unchanged(self):
        assert ss.clean_string_content("hello world") == "hello world"

    def test_local_command_stdout_returns_empty(self):
        text = "<local-command-stdout>foo</local-command-stdout>"
        assert ss.clean_string_content(text) == ""

    def test_command_message_returns_slash_prefixed(self):
        text = "<command-message>test</command-message>"
        result = ss.clean_string_content(text)
        assert result == "/test"

    def test_control_chars_stripped(self):
        text = "hel\x00lo"
        result = ss.clean_string_content(text)
        assert "\x00" not in result
        assert "hello" in result


# ── TestExtractTextBlocks ──────────────────────────────────────────────────────

class TestExtractTextBlocks:
    def test_str_input_returned_cleaned(self):
        result = ss.extract_text_blocks("hello")
        assert result == "hello"

    def test_list_with_text_blocks_joined(self):
        content = [
            {"type": "text", "text": "foo"},
            {"type": "text", "text": "bar"},
        ]
        result = ss.extract_text_blocks(content)
        assert "foo" in result
        assert "bar" in result

    def test_list_non_text_blocks_filtered(self):
        content = [
            {"type": "tool_use", "name": "Bash"},
            {"type": "text", "text": "visible"},
        ]
        result = ss.extract_text_blocks(content)
        assert result == "visible"

    def test_empty_list_returns_empty_string(self):
        assert ss.extract_text_blocks([]) == ""


# ── TestIsSkillOnlySession ─────────────────────────────────────────────────────

class TestIsSkillOnlySession:
    def test_empty_messages_returns_true(self):
        assert ss.is_skill_only_session([]) is True

    def test_messages_empty_list_returns_true(self):
        assert ss.is_skill_only_session([]) is True

    def test_only_custom_skill_returns_true(self):
        # /myskill is not in _META_COMMANDS so this is a skill-only session
        messages = [("user", "/myskill", "2026-01-01T00:00:00Z")]
        assert ss.is_skill_only_session(messages) is True

    def test_regular_prose_message_returns_false(self):
        messages = [("user", "please help me with this task", "2026-01-01T00:00:00Z")]
        assert ss.is_skill_only_session(messages) is False

    def test_ask_user_question_in_tool_counts_returns_false(self):
        messages = [("user", "/myskill", "2026-01-01T00:00:00Z")]
        tool_counts = {"AskUserQuestion": 1}
        assert ss.is_skill_only_session(messages, tool_counts) is False


# ── TestReadWatermark ──────────────────────────────────────────────────────────

class TestReadWatermark:
    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ss, "WATERMARK_PATH", str(tmp_path / ".watermark"))
        assert ss.read_watermark() is None

    def test_valid_iso_timestamp_returns_datetime(self, monkeypatch, tmp_path):
        wm = tmp_path / ".watermark"
        wm.write_text("2026-01-01T00:00:00Z\n")
        monkeypatch.setattr(ss, "WATERMARK_PATH", str(wm))
        result = ss.read_watermark()
        assert result is not None
        assert result.tzinfo is not None


# ── TestReadAllWatermark ───────────────────────────────────────────────────────

class TestReadAllWatermark:
    def test_missing_file_returns_zero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ss, "ALL_WATERMARK_PATH", str(tmp_path / ".all_watermark"))
        assert ss.read_all_watermark() == 0.0

    def test_float_content_returned(self, monkeypatch, tmp_path):
        wm = tmp_path / ".all_watermark"
        wm.write_text("1735689600.5\n")
        monkeypatch.setattr(ss, "ALL_WATERMARK_PATH", str(wm))
        assert ss.read_all_watermark() == 1735689600.5


# ── TestParseSession ───────────────────────────────────────────────────────────

class TestParseSession:
    def test_valid_minimal_jsonl(self, tmp_path):
        p = tmp_path / "session.jsonl"
        _write_jsonl(p, [
            {"type": "message", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z",
             "cwd": "/proj",
             "message": {"role": "user", "content": "hello world"}},
        ])
        data, err = ss.parse_session(str(p))
        assert err is None
        assert data is not None

    def test_returns_required_keys(self, tmp_path):
        p = tmp_path / "session.jsonl"
        _write_jsonl(p, [
            {"type": "message", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z",
             "cwd": "/proj",
             "message": {"role": "user", "content": "hello world"}},
        ])
        data, err = ss.parse_session(str(p))
        assert err is None
        for key in ("messages", "title", "cwd", "first_ts", "last_ts",
                    "models", "input_tokens", "output_tokens", "tool_counts",
                    "first_user_message"):
            assert key in data, f"missing key: {key}"

    def test_bad_file_path_returns_none_and_err(self):
        data, err = ss.parse_session("/nonexistent/path/session.jsonl")
        assert data is None
        assert err is not None
        assert isinstance(err, str)

    def test_token_accumulation(self, tmp_path):
        p = tmp_path / "session.jsonl"
        _write_jsonl(p, [
            {"type": "message", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z",
             "cwd": "/proj",
             "message": {"role": "user", "content": "hello world"}},
            {"type": "message", "uuid": "a1", "timestamp": "2026-01-01T00:01:00Z",
             "message": {"role": "assistant", "content": "ok",
                         "usage": {"input_tokens": 10, "output_tokens": 5}}},
        ])
        data, err = ss.parse_session(str(p))
        assert err is None
        assert data["input_tokens"] == 10
        assert data["output_tokens"] == 5


# ── TestFusedParseJsonl ────────────────────────────────────────────────────────

class TestFusedParseJsonl:
    def _fixture(self, tmp_path):
        p = tmp_path / "session.jsonl"
        _write_jsonl(p, [
            {"type": "message", "uuid": "uuid-u1", "timestamp": "2026-01-01T00:00:00Z",
             "cwd": "/proj",
             "message": {"role": "user", "content": "hello world"}},
            {"type": "message", "uuid": "uuid-a1", "timestamp": "2026-01-01T00:01:00Z",
             "message": {"role": "assistant", "content": "hi there",
                         "usage": {"input_tokens": 8, "output_tokens": 4}}},
        ])
        return p

    def test_returns_last_msg_uuid(self, tmp_path):
        """_fused_parse_jsonl includes last_msg_uuid matching last user/assistant message."""
        p = self._fixture(tmp_path)
        data, err = ss._fused_parse_jsonl(str(p))
        assert err is None
        assert data is not None
        assert data["last_msg_uuid"] == "uuid-a1"

    def test_messages_contain_uuid_field(self, tmp_path):
        """Each message dict in the fused result has a uuid field."""
        p = self._fixture(tmp_path)
        data, err = ss._fused_parse_jsonl(str(p))
        assert err is None
        for msg in data["messages"]:
            assert "uuid" in msg
        assert data["messages"][0]["uuid"] == "uuid-u1"
        assert data["messages"][1]["uuid"] == "uuid-a1"

    def test_single_open_call(self, tmp_path):
        """_fused_parse_jsonl opens the JSONL file exactly once (no double-read)."""
        from unittest.mock import patch as _patch
        p = self._fixture(tmp_path)
        target_path = str(p)
        real_open = open
        open_count = []

        def _counting_open(file, *args, **kwargs):
            if str(file) == target_path:
                open_count.append(1)
            return real_open(file, *args, **kwargs)

        with _patch("builtins.open", side_effect=_counting_open):
            data, err = ss._fused_parse_jsonl(target_path)

        assert err is None
        assert data is not None
        assert len(open_count) == 1, f"expected 1 open call, got {len(open_count)}"

    def test_metadata_equivalent_to_parse_session(self, tmp_path):
        """_fused_parse_jsonl and parse_session produce identical metadata."""
        p = self._fixture(tmp_path)
        fused, err_f = ss._fused_parse_jsonl(str(p))
        parsed, err_p = ss.parse_session(str(p))
        assert err_f is None and err_p is None
        for key in ("title", "cwd", "first_ts", "last_ts", "input_tokens", "output_tokens"):
            assert fused[key] == parsed[key], f"mismatch on {key}"

    def test_scan_sessions_skips_compact_summary(self):
        import json, tempfile, os
        lines = [
            {"message": {"role": "user", "content": "q"},
             "timestamp": "2025-01-01T00:00:00Z", "uuid": "u1"},
            {"isCompactSummary": True,
             "message": {"role": "assistant", "content": "summary",
                         "usage": {"input_tokens": 999, "output_tokens": 999}},
             "timestamp": "2025-01-01T00:00:01Z", "uuid": "compact-uuid"},
            {"message": {"role": "assistant", "content": "a",
                         "usage": {"input_tokens": 0, "output_tokens": 3}},
             "timestamp": "2025-01-01T00:00:02Z", "uuid": "u2"},
        ]
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for l in lines:
            tmp.write(json.dumps(l) + "\n")
        tmp.close()
        data, err = ss._fused_parse_jsonl(tmp.name)
        texts = [m["text"] if isinstance(m, dict) else m[1] for m in data["messages"]]
        assert "summary" not in texts
        assert data.get("last_msg_uuid") == "u2"
        os.unlink(tmp.name)

    def test_scan_sessions_command_args_fence(self):
        text = (
            "<command-name>cmd</command-name>"
            "<command-message>cmd</command-message>"
            "<command-args>```\nfoo\n```</command-args>"
        )
        out = ss.clean_string_content(text)
        assert out == "/cmd\n\n````\n```\nfoo\n```\n````"
