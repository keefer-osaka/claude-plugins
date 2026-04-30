import sys
import os

_base = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/kb-ingest/scripts'))
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/_lib'))

import json
import re
from unittest.mock import patch, MagicMock
import pytest

import transcript_utils as tu


# ── make_slug ─────────────────────────────────────────────────────────────────

def test_make_slug_basic():
    assert tu.make_slug("Hello World") == "hello-world"


def test_make_slug_empty():
    assert tu.make_slug("") == "untitled"


def test_make_slug_none_like():
    assert tu.make_slug("   ") == "untitled"


def test_make_slug_removes_parens():
    assert tu.make_slug("My Topic (extra)") == "my-topic"


def test_make_slug_removes_full_width_parens():
    assert tu.make_slug("主題（括號內）說明") == "主題說明"


def test_make_slug_max_len():
    long = "a" * 100
    result = tu.make_slug(long, max_len=10)
    assert len(result) <= 10


def test_make_slug_collapses_dashes():
    assert "--" not in tu.make_slug("foo   bar")


# ── make_transcript_filename ──────────────────────────────────────────────────

def test_make_transcript_filename_structure():
    fname = tu.make_transcript_filename("2026-04-10T06:00:00Z", "abcdef1234567890", "My Chat")
    assert fname.startswith("2026-04-10-abcdef12-")
    assert fname.endswith(".md")


def test_make_transcript_filename_short_session():
    fname = tu.make_transcript_filename("2026-04-10T06:00:00Z", "abc", "title")
    assert "abc" in fname


def test_make_transcript_filename_bad_ts():
    fname = tu.make_transcript_filename("not-a-timestamp", "sid123456", "title")
    assert fname.endswith(".md")
    assert "sid12345" in fname


# ── format_message_header ─────────────────────────────────────────────────────

def test_format_message_header_user():
    header = tu.format_message_header("user", "2026-04-10T06:00:00Z")
    assert header.startswith("## User (")
    assert "2026-04-10" in header


def test_format_message_header_assistant():
    header = tu.format_message_header("assistant", "2026-04-10T06:00:00Z")
    assert header.startswith("## Assistant (")


def test_format_message_header_bad_ts():
    header = tu.format_message_header("user", "bad-ts")
    assert "User" in header
    assert "bad-ts" in header


# ── render_transcript_md ──────────────────────────────────────────────────────

def _make_messages():
    return [
        {"role": "user", "text": "Hello", "timestamp": "2026-04-10T06:00:00Z", "uuid": "u1"},
        {"role": "assistant", "text": "Hi there", "timestamp": "2026-04-10T06:01:00Z", "uuid": "u2"},
    ]


def test_render_transcript_md_frontmatter():
    md = tu.render_transcript_md(
        session_id="sess-001",
        title="Test Session",
        cwd="/tmp",
        date="2026-04-10",
        first_ts="2026-04-10T06:00:00Z",
        last_ts="2026-04-10T06:01:00Z",
        message_count=2,
        last_processed_msg_uuid="u2",
        last_processed_at="2026-04-10T06:02:00Z",
        models=["claude-3"],
        derived_pages=["wiki/page.md"],
        status="processed",
        messages=_make_messages(),
    )
    assert md.startswith("---")
    assert "session_id: sess-001" in md
    assert "title: Test Session" in md
    assert "status: processed" in md


def test_render_transcript_md_body_contains_messages():
    md = tu.render_transcript_md(
        session_id="sess-002",
        title="Chat",
        cwd="/tmp",
        date="2026-04-10",
        first_ts="2026-04-10T06:00:00Z",
        last_ts="2026-04-10T06:01:00Z",
        message_count=2,
        last_processed_msg_uuid="u2",
        last_processed_at="2026-04-10T06:02:00Z",
        models=[],
        derived_pages=[],
        status="processed",
        messages=_make_messages(),
    )
    assert "Hello" in md
    assert "Hi there" in md
    assert "## User" in md
    assert "## Assistant" in md


def test_render_transcript_md_delta_marker():
    md = tu.render_transcript_md(
        session_id="s", title="t", cwd="/", date="2026-04-10",
        first_ts="2026-04-10T06:00:00Z", last_ts="2026-04-10T06:00:00Z",
        message_count=1, last_processed_msg_uuid="uuid-abc",
        last_processed_at="2026-04-10T06:00:00Z",
        models=[], derived_pages=[], status="raw",
        messages=[{"role": "user", "text": "hi", "timestamp": "2026-04-10T06:00:00Z"}],
    )
    assert "<!-- delta marker: last_processed_msg_uuid=uuid-abc -->" in md


def test_render_transcript_md_skips_empty_messages():
    messages = [
        {"role": "user", "text": "", "timestamp": "2026-04-10T06:00:00Z"},
        {"role": "assistant", "text": "Response", "timestamp": "2026-04-10T06:01:00Z"},
    ]
    md = tu.render_transcript_md(
        session_id="s", title="t", cwd="/", date="2026-04-10",
        first_ts="2026-04-10T06:00:00Z", last_ts="2026-04-10T06:01:00Z",
        message_count=1, last_processed_msg_uuid="", last_processed_at="",
        models=[], derived_pages=[], status="raw", messages=messages,
    )
    assert "## User" not in md
    assert "Response" in md


def test_render_transcript_md_author_line():
    md = tu.render_transcript_md(
        session_id="s", title="t", cwd="/", date="2026-04-10",
        first_ts="", last_ts="", message_count=0, last_processed_msg_uuid="",
        last_processed_at="", models=[], derived_pages=[], status="raw",
        messages=[], author="keefer",
    )
    assert "author: keefer" in md


# ── upsert_session_manifest ───────────────────────────────────────────────────

def test_upsert_session_manifest_new_entry():
    manifest = {}
    tu.upsert_session_manifest(
        manifest, "sid-1", "transcripts/foo.md", "uuid-last", "2026-04-10T06:00:00Z",
        5, "processed", ["wiki/a.md"]
    )
    assert "sid-1" in manifest
    entry = manifest["sid-1"]
    assert entry["transcript_path"] == "transcripts/foo.md"
    assert entry["message_count"] == 5
    assert "wiki/a.md" in entry["derived_pages"]


def test_upsert_session_manifest_merges_derived_pages():
    manifest = {"sid-1": {"derived_pages": ["wiki/a.md"], "author": ""}}
    tu.upsert_session_manifest(
        manifest, "sid-1", "transcripts/foo.md", "uuid-last", "2026-04-10T06:00:00Z",
        5, "processed", ["wiki/b.md"]
    )
    assert "wiki/a.md" in manifest["sid-1"]["derived_pages"]
    assert "wiki/b.md" in manifest["sid-1"]["derived_pages"]


def test_upsert_session_manifest_author_conflict():
    manifest = {"sid-1": {"derived_pages": [], "author": "alice"}}
    tu.upsert_session_manifest(
        manifest, "sid-1", "transcripts/foo.md", "uuid-last", "2026-04-10T06:00:00Z",
        3, "processed", [], author="bob"
    )
    assert manifest["sid-1"].get("author_conflict") is True


def test_upsert_session_manifest_no_conflict_same_author():
    manifest = {"sid-1": {"derived_pages": [], "author": "alice"}}
    tu.upsert_session_manifest(
        manifest, "sid-1", "transcripts/foo.md", "uuid-last", "2026-04-10T06:00:00Z",
        3, "processed", [], author="alice"
    )
    assert not manifest["sid-1"].get("author_conflict")


# ── read_sessions_json / write_sessions_json ──────────────────────────────────

def test_read_sessions_json_missing(tmp_path):
    with patch.object(tu, "SESSIONS_JSON_PATH", str(tmp_path / "sessions.json")):
        result = tu.read_sessions_json()
    assert result == {}


def test_write_and_read_sessions_json(tmp_path):
    path = str(tmp_path / "sessions.json")
    data = {"sid-1": {"transcript_path": "foo.md"}}
    with patch.object(tu, "SESSIONS_JSON_PATH", path):
        tu.write_sessions_json(data)
        result = tu.read_sessions_json()
    assert result == data


def test_read_sessions_json_invalid_json(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text("not json", encoding="utf-8")
    with patch.object(tu, "SESSIONS_JSON_PATH", str(path)):
        result = tu.read_sessions_json()
    assert result == {}


# ── append_delta_to_transcript ────────────────────────────────────────────────

def _make_base_transcript(session_id="sess-1", last_uuid="old-uuid"):
    return f"""---
session_id: {session_id}
title: Test
cwd: /tmp
date: 2026-04-10
first_ts: 2026-04-10T06:00:00Z
last_ts: 2026-04-10T06:00:00Z
message_count: 1
last_processed_msg_uuid: {last_uuid}
last_processed_at: 2026-04-10T06:00:00Z
models: []
derived_pages: []
status: raw
source: jsonl
---

# Test

> Session `sess-000`｜2026-04-10｜1 messages

## User (2026-04-10 14:00)

Hello

---

<!-- delta marker: last_processed_msg_uuid={last_uuid} -->
"""


def test_append_delta_adds_messages(tmp_path):
    transcript_path = str(tmp_path / "transcript.md")
    content = _make_base_transcript()
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(content)

    new_msgs = [{"role": "assistant", "text": "New response", "timestamp": "2026-04-10T07:00:00Z"}]
    result = tu.append_delta_to_transcript(transcript_path, new_msgs, "new-uuid")

    assert result is True
    updated = open(transcript_path, encoding="utf-8").read()
    assert "New response" in updated
    assert "new-uuid" in updated


def test_append_delta_updates_frontmatter(tmp_path):
    transcript_path = str(tmp_path / "transcript.md")
    content = _make_base_transcript(last_uuid="old-uuid")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(content)

    new_msgs = [{"role": "user", "text": "Follow-up", "timestamp": "2026-04-10T07:00:00Z"}]
    tu.append_delta_to_transcript(transcript_path, new_msgs, "new-uuid-123")

    updated = open(transcript_path, encoding="utf-8").read()
    assert "last_processed_msg_uuid: new-uuid-123" in updated
    assert "status: processed" in updated


def test_append_delta_no_marker_returns_false(tmp_path):
    transcript_path = str(tmp_path / "transcript.md")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write("# No marker here\n\nSome content\n")

    result = tu.append_delta_to_transcript(transcript_path, [{"role": "user", "text": "hi", "timestamp": ""}], "uuid")
    assert result is False


def test_append_delta_empty_messages_returns_false(tmp_path):
    transcript_path = str(tmp_path / "transcript.md")
    content = _make_base_transcript()
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(content)

    result = tu.append_delta_to_transcript(transcript_path, [], "new-uuid")
    assert result is False


def test_append_delta_skips_empty_text(tmp_path):
    transcript_path = str(tmp_path / "transcript.md")
    content = _make_base_transcript()
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(content)

    new_msgs = [{"role": "user", "text": "   ", "timestamp": "2026-04-10T07:00:00Z"}]
    result = tu.append_delta_to_transcript(transcript_path, new_msgs, "new-uuid")
    assert result is False


def test_append_delta_increments_message_count(tmp_path):
    transcript_path = str(tmp_path / "transcript.md")
    content = _make_base_transcript()
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(content)

    new_msgs = [
        {"role": "user", "text": "msg1", "timestamp": "2026-04-10T07:00:00Z"},
        {"role": "assistant", "text": "msg2", "timestamp": "2026-04-10T07:01:00Z"},
    ]
    tu.append_delta_to_transcript(transcript_path, new_msgs, "new-uuid")
    updated = open(transcript_path, encoding="utf-8").read()
    assert "message_count: 3" in updated


# ── rebuild_transcripts_index ─────────────────────────────────────────────────

def test_rebuild_transcripts_index(tmp_path):
    td = tmp_path / "transcripts"
    td.mkdir()
    (td / "2026-04-10-abcdef12-test.md").write_text(
        "---\nsession_id: abcdef1234567890\ntitle: My Chat\ndate: 2026-04-10\nstatus: processed\n---\n\nBody\n",
        encoding="utf-8",
    )
    tu.rebuild_transcripts_index(str(td))
    index = (td / "_index.md").read_text(encoding="utf-8")
    assert "My Chat" in index
    assert "2026-04-10" in index
    assert "processed" in index


def test_rebuild_transcripts_index_skips_index_file(tmp_path):
    td = tmp_path / "transcripts"
    td.mkdir()
    (td / "_index.md").write_text("# old index\n", encoding="utf-8")
    tu.rebuild_transcripts_index(str(td))
    index = (td / "_index.md").read_text(encoding="utf-8")
    assert "Transcripts Index" in index


def test_rebuild_transcripts_index_sorted_desc(tmp_path):
    td = tmp_path / "transcripts"
    td.mkdir()
    for date in ["2026-03-01", "2026-04-10", "2026-02-15"]:
        (td / f"{date}-aabbccdd-chat.md").write_text(
            f"---\nsession_id: aabbccdd1234\ntitle: Chat {date}\ndate: {date}\nstatus: raw\n---\n\nBody\n",
            encoding="utf-8",
        )
    tu.rebuild_transcripts_index(str(td))
    index = (td / "_index.md").read_text(encoding="utf-8")
    pos_apr = index.find("2026-04-10")
    pos_mar = index.find("2026-03-01")
    pos_feb = index.find("2026-02-15")
    assert pos_apr < pos_mar < pos_feb


# ── get_last_message_uuid ─────────────────────────────────────────────────────

def test_get_last_message_uuid(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"uuid": "u1", "message": {"role": "user"}}),
        json.dumps({"uuid": "u2", "message": {"role": "assistant"}}),
        json.dumps({"isMeta": True, "uuid": "meta-u3", "message": {"role": "user"}}),
    ]
    jsonl.write_text("\n".join(lines), encoding="utf-8")
    result = tu.get_last_message_uuid(str(jsonl))
    assert result == "u2"


def test_get_last_message_uuid_missing_file():
    result = tu.get_last_message_uuid("/nonexistent/path.jsonl")
    assert result == ""


def test_get_last_message_uuid_skips_meta(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"uuid": "u1", "message": {"role": "user"}}),
        json.dumps({"isMeta": True, "uuid": "meta-u2", "message": {"role": "user"}}),
    ]
    jsonl.write_text("\n".join(lines), encoding="utf-8")
    result = tu.get_last_message_uuid(str(jsonl))
    assert result == "u1"


def test_get_last_message_uuid_empty_file(tmp_path):
    jsonl = tmp_path / "empty.jsonl"
    jsonl.write_text("", encoding="utf-8")
    result = tu.get_last_message_uuid(str(jsonl))
    assert result == ""


# ── scan_wiki_sources ─────────────────────────────────────────────────────────

def test_scan_wiki_sources(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    page = wiki_dir / "page.md"
    page.write_text(
        "---\nsources:\n  - session: sid-abc\n    date: 2026-04-10\n---\n\nBody\n",
        encoding="utf-8",
    )
    result = tu.scan_wiki_sources(str(wiki_dir))
    assert "sid-abc" in result
    assert any("page.md" in p for p in result["sid-abc"])


def test_scan_wiki_sources_empty_dir(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    result = tu.scan_wiki_sources(str(wiki_dir))
    assert result == {}


# ── add_transcript_to_wiki_sources ────────────────────────────────────────────

def _make_wiki_page(session_id="sid-001", has_transcript=False):
    transcript_line = f'    transcript: "[[2026-04-10-sid-001-chat]]"\n' if has_transcript else ""
    return f"""---
title: My Page
sources:
  - session: {session_id}
    date: 2026-04-10
{transcript_line}created: 2026-04-10
---

Body text here.
"""


def test_add_transcript_adds_field(tmp_path):
    wiki_path = str(tmp_path / "page.md")
    with open(wiki_path, "w", encoding="utf-8") as f:
        f.write(_make_wiki_page("sid-001", has_transcript=False))

    result = tu.add_transcript_to_wiki_sources(
        wiki_path, {"sid-001": "transcripts/2026-04-10-sid-001-chat.md"}
    )
    # v0.4.0: returns {"modified": bool, "added": [...]}
    assert result["modified"] is True
    content = open(wiki_path, encoding="utf-8").read()
    assert 'transcript:' in content
    assert "2026-04-10-sid-001-chat" in content


def test_add_transcript_no_change_if_already_present(tmp_path):
    wiki_path = str(tmp_path / "page.md")
    with open(wiki_path, "w", encoding="utf-8") as f:
        f.write(_make_wiki_page("sid-001", has_transcript=True))

    result = tu.add_transcript_to_wiki_sources(
        wiki_path, {"sid-001": "transcripts/2026-04-10-sid-001-chat.md"}
    )
    assert result["modified"] is False


def test_add_transcript_no_match_returns_false(tmp_path):
    wiki_path = str(tmp_path / "page.md")
    with open(wiki_path, "w", encoding="utf-8") as f:
        f.write(_make_wiki_page("sid-001"))

    result = tu.add_transcript_to_wiki_sources(wiki_path, {"other-sid": "transcripts/foo.md"})
    assert result["modified"] is False


def test_add_transcript_no_frontmatter_returns_false(tmp_path):
    wiki_path = str(tmp_path / "page.md")
    with open(wiki_path, "w", encoding="utf-8") as f:
        f.write("# No frontmatter\n\nJust body.\n")

    result = tu.add_transcript_to_wiki_sources(wiki_path, {"sid-001": "foo.md"})
    assert result["modified"] is False


# ── P2: wiki_index read/write/build/incremental ───────────────────────────────

def _make_wiki_page_with_session(path, session_id):
    path.write_text(
        f"---\ntitle: test\nsources:\n  - session: {session_id}\n    date: 2026-04-21\n---\n# test\n",
        encoding="utf-8",
    )


def test_read_wiki_index_returns_none_when_missing(tmp_path):
    result = tu.read_wiki_index(str(tmp_path))
    assert result is None


def test_write_read_wiki_index_roundtrip(tmp_path):
    (tmp_path / "_schema").mkdir()
    data = {"schema_version": 1, "generated_at": "2026-04-21T00:00:00Z", "session_to_wiki": {"sid-x": ["wiki/p.md"]}}
    tu.write_wiki_index(data, str(tmp_path))
    result = tu.read_wiki_index(str(tmp_path))
    assert result == data


def test_write_wiki_index_atomic(tmp_path, monkeypatch):
    """If os.replace crashes after .tmp write, wiki_index.json must not exist."""
    (tmp_path / "_schema").mkdir()
    import os
    original_replace = os.replace

    def crash_replace(src, dst):
        if dst.endswith("wiki_index.json"):
            raise RuntimeError("simulated crash")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", crash_replace)
    with pytest.raises(RuntimeError):
        tu.write_wiki_index({"schema_version": 1, "session_to_wiki": {}}, str(tmp_path))

    assert not (tmp_path / "_schema" / "wiki_index.json").exists()


def test_build_wiki_index_from_scan_creates_file(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "_schema").mkdir()
    _make_wiki_page_with_session(vault / "wiki" / "p.md", "sid-abc")
    monkeypatch.setattr(tu, "VAULT_DIR", str(vault))
    monkeypatch.setattr(tu, "WIKI_DIR", str(vault / "wiki"))

    result = tu.build_wiki_index_from_scan(str(vault / "wiki"), str(vault))
    assert result["schema_version"] == 1
    assert "sid-abc" in result["session_to_wiki"]
    assert (vault / "_schema" / "wiki_index.json").exists()


def test_backfill_incremental_noop_when_no_touched(tmp_path):
    manifest = {"sid-a": {"transcript_path": "transcripts/t.md"}}
    wiki_index = {"session_to_wiki": {"sid-a": ["wiki/p.md"]}}
    result = tu.backfill_wiki_transcripts_incremental(manifest, str(tmp_path / "wiki"), [], wiki_index, str(tmp_path))
    assert result == 0


def test_backfill_incremental_noop_when_index_none(tmp_path):
    manifest = {"sid-a": {"transcript_path": "transcripts/t.md"}}
    result = tu.backfill_wiki_transcripts_incremental(manifest, str(tmp_path / "wiki"), ["sid-a"], None, str(tmp_path))
    assert result == 0


def test_backfill_incremental_only_touches_mapped_pages(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    _make_wiki_page_with_session(vault / "wiki" / "page_a.md", "sid-a")
    _make_wiki_page_with_session(vault / "wiki" / "page_b.md", "sid-b")

    manifest = {
        "sid-a": {"transcript_path": "transcripts/2026-04-21-sida-title.md"},
        "sid-b": {"transcript_path": "transcripts/2026-04-21-sidb-title.md"},
    }
    wiki_index = {
        "session_to_wiki": {
            "sid-a": ["wiki/page_a.md"],
            "sid-b": ["wiki/page_b.md"],
        }
    }

    result = tu.backfill_wiki_transcripts_incremental(
        manifest, str(vault / "wiki"), ["sid-a"], wiki_index, str(vault)
    )
    assert result == 1
    content_a = (vault / "wiki" / "page_a.md").read_text(encoding="utf-8")
    assert "transcript:" in content_a
    content_b = (vault / "wiki" / "page_b.md").read_text(encoding="utf-8")
    assert "transcript:" not in content_b


def test_backfill_incremental_skips_already_has_transcript(tmp_path):
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "p.md").write_text(
        "---\ntitle: t\nsources:\n  - session: sid-c\n    date: 2026-04-21\n    transcript: \"[[foo]]\"\n---\n# t\n",
        encoding="utf-8",
    )
    manifest = {"sid-c": {"transcript_path": "transcripts/foo.md"}}
    wiki_index = {"session_to_wiki": {"sid-c": ["wiki/p.md"]}}

    result = tu.backfill_wiki_transcripts_incremental(
        manifest, str(vault / "wiki"), ["sid-c"], wiki_index, str(vault)
    )
    assert result == 0


# ── P3: rebuild_transcripts_index_from_manifest ───────────────────────────────

def test_rebuild_from_manifest_produces_index(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    manifest = {
        "sid-1": {"transcript_path": "transcripts/2026-04-21-sid1-title.md", "title": "Title One", "status": "processed"},
    }
    tu.rebuild_transcripts_index_from_manifest(manifest, str(transcripts_dir))
    content = (transcripts_dir / "_index.md").read_text(encoding="utf-8")
    assert "Title One" in content
    assert "| 日期 | 標題 | Session | 狀態 |" in content


def test_rebuild_from_manifest_sort_desc_by_date(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    manifest = {
        "sid-a": {"transcript_path": "transcripts/2026-01-01-sida-old.md", "title": "Old", "status": "processed"},
        "sid-b": {"transcript_path": "transcripts/2026-04-21-sidb-new.md", "title": "New", "status": "processed"},
        "sid-c": {"transcript_path": "transcripts/2025-12-31-sidc-oldest.md", "title": "Oldest", "status": "processed"},
    }
    tu.rebuild_transcripts_index_from_manifest(manifest, str(transcripts_dir))
    content = (transcripts_dir / "_index.md").read_text(encoding="utf-8")
    dates = re.findall(r'\| (\d{4}-\d{2}-\d{2}) \|', content)
    assert dates == sorted(dates, reverse=True)


def test_rebuild_from_manifest_matches_legacy_output(tmp_path):
    """manifest-driven and filesystem-scan outputs match (ignoring timestamp line)."""
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()

    fname1 = "2026-04-21-aabbccdd-first.md"
    fname2 = "2026-04-20-11223344-second.md"

    (transcripts_dir / fname1).write_text(
        "---\nsession_id: aabbccdd1234\ntitle: First\ndate: 2026-04-21\nstatus: processed\n---\n# First\n",
        encoding="utf-8",
    )
    (transcripts_dir / fname2).write_text(
        "---\nsession_id: 112233441234\ntitle: Second\ndate: 2026-04-20\nstatus: processed\n---\n# Second\n",
        encoding="utf-8",
    )

    # Legacy output
    tu.rebuild_transcripts_index(str(transcripts_dir))
    legacy = (transcripts_dir / "_index.md").read_text(encoding="utf-8")

    # Manifest-driven output
    manifest = {
        "aabbccdd1234": {"transcript_path": f"transcripts/{fname1}", "title": "First", "status": "processed"},
        "112233441234": {"transcript_path": f"transcripts/{fname2}", "title": "Second", "status": "processed"},
    }
    tu.rebuild_transcripts_index_from_manifest(manifest, str(transcripts_dir))
    new_out = (transcripts_dir / "_index.md").read_text(encoding="utf-8")

    def drop_ts(text):
        return [l for l in text.splitlines() if not l.startswith("> 最後更新：")]

    assert drop_ts(legacy) == drop_ts(new_out)
