import sys
import os

_base = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/kb-import/scripts'))
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/kb-ingest/scripts'))
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/_lib'))

import pytest
import scan_markdown as sm


# ── TestAuthorFromZipName ──────────────────────────────────────────────────────

class TestAuthorFromZipName:
    def test_basic_match(self):
        assert sm.author_from_zip_name("chat-logs-alice-20260417.zip") == "alice"

    def test_extra_suffix_after_date(self):
        assert sm.author_from_zip_name("chat-logs-alice-20260417-extra.zip") == "alice"

    def test_no_match_returns_unknown(self):
        assert sm.author_from_zip_name("random.zip") == "unknown"

    def test_full_path_extracts_author(self):
        assert sm.author_from_zip_name("/some/dir/chat-logs-bob-20260101.zip") == "bob"


# ── TestAuthorFromDir ─────────────────────────────────────────────────────────

class TestAuthorFromDir:
    def test_author_txt_present(self, tmp_path):
        (tmp_path / "author.txt").write_text("alice\n")
        assert sm.author_from_dir(str(tmp_path)) == "alice"

    def test_empty_author_txt_returns_unknown(self, tmp_path):
        (tmp_path / "author.txt").write_text("")
        assert sm.author_from_dir(str(tmp_path)) == "unknown"

    def test_no_author_txt_returns_unknown(self, tmp_path):
        assert sm.author_from_dir(str(tmp_path)) == "unknown"


# ── TestTsFromHeading ─────────────────────────────────────────────────────────

class TestTsFromHeading:
    # _ts_from_heading returns (iso_ts, tz_label) since v0.4.0

    def test_empty_string(self):
        assert sm._ts_from_heading("") == ("", "")

    def test_iso_with_timezone_suffix(self):
        ts, label = sm._ts_from_heading("2026-04-17 12:34 UTC+8")
        assert ts == "2026-04-17T12:34+08:00"
        assert label == "UTC+8"

    def test_exact_iso_no_suffix(self):
        ts, label = sm._ts_from_heading("2026-04-17 12:34")
        assert ts == "2026-04-17T12:34"
        assert label == ""

    def test_non_date_string_returned_as_is(self):
        ts, label = sm._ts_from_heading("some-non-date-string")
        assert ts == "some-non-date-string"
        assert label == ""


# ── TestHtmlToMd ──────────────────────────────────────────────────────────────

class TestHtmlToMd:
    def test_empty_string(self):
        assert sm._html_to_md("") == ""

    def test_inline_code(self):
        assert sm._html_to_md("<code>x</code>") == "`x`"

    def test_bold(self):
        assert sm._html_to_md("<strong>hi</strong>") == "**hi**"

    def test_fenced_code_block_with_language(self):
        html = '<pre><code class="language-python">print("x")</code></pre>'
        assert sm._html_to_md(html) == '```python\nprint("x")\n```'

    def test_html_entity_unescape(self):
        assert sm._html_to_md("&lt;tag&gt;") == "<tag>"

    def test_heading_h1(self):
        assert sm._html_to_md("<h1>Title</h1>") == "# Title"


# ── TestParseMdFile ───────────────────────────────────────────────────────────

class TestParseMdFile:
    def _write(self, path, content):
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_session_id_extracted(self, tmp_path):
        p = self._write(tmp_path / "s.md", "<!-- sid: abc123 -->\n### User\nhello\n")
        assert sm.parse_md_file(p)["session_id"] == "abc123"

    def test_git_user_extracted(self, tmp_path):
        p = self._write(tmp_path / "s.md", "<!-- git_user: alice -->\n### User\nhello\n")
        assert sm.parse_md_file(p)["git_user"] == "alice"

    def test_single_user_message(self, tmp_path):
        p = self._write(tmp_path / "s.md", "<!-- sid: x -->\n### User\nhello world\n")
        result = sm.parse_md_file(p)
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert "hello world" in result["messages"][0]["text"]

    def test_user_and_assistant_messages(self, tmp_path):
        content = "<!-- sid: x -->\n### User\nhello\n---\n### Assistant\nhi there\n"
        p = self._write(tmp_path / "s.md", content)
        result = sm.parse_md_file(p)
        assert len(result["messages"]) == 2
        assert result["messages"][1]["role"] == "assistant"

    def test_horizontal_rule_not_in_body(self, tmp_path):
        content = "### User\nhello\n---\n### Assistant\nresponse\n"
        p = self._write(tmp_path / "s.md", content)
        for msg in sm.parse_md_file(p)["messages"]:
            assert "---" not in msg["text"]

    def test_uuid_extracted(self, tmp_path):
        content = "<!-- uuid: myuuid -->\n### User\nhello\n"
        p = self._write(tmp_path / "s.md", content)
        assert sm.parse_md_file(p)["messages"][0]["uuid"] == "myuuid"

    def test_no_session_id_empty_string(self, tmp_path):
        p = self._write(tmp_path / "s.md", "### User\nhello\n")
        assert sm.parse_md_file(p)["session_id"] == ""

    def test_nonexistent_file_returns_none(self):
        assert sm.parse_md_file("/nonexistent/file.md") is None

    def test_role_mapping_localized(self, tmp_path):
        p = self._write(tmp_path / "s.md", "### 使用者\nhello\n")
        assert sm.parse_md_file(p)["messages"][0]["role"] == "user"


# ── TestParseHtmlFile ─────────────────────────────────────────────────────────

class TestParseHtmlFile:
    _MSG = (
        '<!-- uuid: {uuid} -->'
        '<div class="message {role}">'
        '<div class="msg-header">'
        '<span class="msg-role">{role}</span>'
        '<span class="msg-time">{ts}</span>'
        '</div>'
        '<div class="msg-body">{body}</div>'
        '</div>'
    )

    def _write(self, path, body_content):
        content = (
            "<html><body>\n"
            "<!-- sid: sid123 --><!-- git_user: bob -->\n"
            f"{body_content}\n"
            "</body></html>"
        )
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_session_id_extracted(self, tmp_path):
        p = self._write(tmp_path / "s.html", "")
        assert sm.parse_html_file(p)["session_id"] == "sid123"

    def test_git_user_extracted(self, tmp_path):
        p = self._write(tmp_path / "s.html", "")
        assert sm.parse_html_file(p)["git_user"] == "bob"

    def test_single_message_parsed(self, tmp_path):
        msg = self._MSG.format(uuid="u1", role="user", ts="", body="<p>Hello</p>")
        p = self._write(tmp_path / "s.html", msg)
        result = sm.parse_html_file(p)
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert "Hello" in result["messages"][0]["text"]

    def test_multiple_messages(self, tmp_path):
        msg1 = self._MSG.format(uuid="u1", role="user", ts="", body="<p>Hi</p>")
        msg2 = self._MSG.format(uuid="u2", role="assistant", ts="", body="<p>Hey</p>")
        p = self._write(tmp_path / "s.html", msg1 + msg2)
        assert len(sm.parse_html_file(p)["messages"]) == 2

    def test_nonexistent_file_returns_none(self):
        assert sm.parse_html_file("/nonexistent/file.html") is None


# ── TestScanDirSmoke ──────────────────────────────────────────────────────────

class TestScanDirSmoke:
    def _write_session_md(self, path, sid="sess1", git_user="alice"):
        path.write_text(
            f"<!-- sid: {sid} -->\n<!-- git_user: {git_user} -->\n"
            "<!-- uuid: u1 -->\n### User\nhello world\n",
            encoding="utf-8",
        )

    def test_new_session_produces_entry(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sm, "read_sessions_json", lambda: {})
        monkeypatch.setattr(sm, "VAULT_DIR", str(tmp_path))
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        self._write_session_md(inbox / "session.md", sid="new-sess-1")
        results, _ = sm.scan_dir(str(inbox), "alice")
        assert len(results) == 1
        assert results[0]["session_id"] == "new-sess-1"
        assert results[0]["delta"] is False

    def test_already_ingested_session_skipped(self, monkeypatch, tmp_path):
        trans_dir = tmp_path / "transcripts"
        trans_dir.mkdir()
        (trans_dir / "2026-01-01-existing.md").write_text("# transcript")
        manifest = {"ingest-sess-1": {"transcript_path": "transcripts/2026-01-01-existing.md"}}
        monkeypatch.setattr(sm, "read_sessions_json", lambda: manifest)
        monkeypatch.setattr(sm, "VAULT_DIR", str(tmp_path))
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        self._write_session_md(inbox / "session.md", sid="ingest-sess-1")
        results, _ = sm.scan_dir(str(inbox), "alice")
        assert all(r["session_id"] != "ingest-sess-1" for r in results)
