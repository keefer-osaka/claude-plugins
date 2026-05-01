"""Unit tests for remap_wiki_session_prefix.py.

Coverage:
  - regex correctness (exact / extended / inline)
  - four rules (R1 / R2 / R3 / R4)
  - idempotency (apply twice → no drift)
  - backup creation on --apply
"""

import json
import os
import sys

import pytest

_BASE = os.path.dirname(__file__)
sys.path.insert(
    0,
    os.path.join(_BASE, "../../plugins/obsidian-kb/vault-payload/.claude/skills/kb-ingest/scripts"),
)
sys.path.insert(
    0,
    os.path.join(_BASE, "../../plugins/obsidian-kb/vault-payload/.claude/skills/_lib"),
)

import remap_wiki_session_prefix as rmp  # noqa: E402


# ── fixture helpers ───────────────────────────────────────────────────────────

def _make_vault(tmp_path, sessions: dict, wiki_files: dict[str, str]):
    """Build a minimal vault layout. wiki_files maps relative path → content."""
    vault = tmp_path / "vault"
    (vault / "_schema").mkdir(parents=True)
    (vault / "wiki").mkdir(parents=True)
    (vault / "_schema" / "sessions.json").write_text(
        json.dumps(sessions, ensure_ascii=False), encoding="utf-8"
    )
    for rel, content in wiki_files.items():
        target = vault / "wiki" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return vault


def _wiki_with_session(prefix: str) -> str:
    return (
        "---\n"
        "type: source\n"
        "sources:\n"
        f"  - session: {prefix}\n"
        "    date: 2026-04-18\n"
        "---\n"
        "\n"
        "Body text.\n"
    )


# ── regex correctness ────────────────────────────────────────────────────────

def test_regex_matches_exact_prefix():
    text = "  - session: 2026-04-18_PK-7348\n"
    new, n = rmp.rewrite_session_line(
        text, "2026-04-18_PK-7348", "2026-04-18_PK-7348-FULL"
    )
    assert n == 1
    assert "FULL" in new
    assert new == "  - session: 2026-04-18_PK-7348-FULL\n"


def test_regex_does_not_match_extended_prefix():
    """Critic Major #3: extended prefix must NOT match."""
    text = "  - session: 2026-04-18_PK-7348-extra\n"
    new, n = rmp.rewrite_session_line(
        text, "2026-04-18_PK-7348", "2026-04-18_PK-7348-FULL"
    )
    assert n == 0
    assert new == text


def test_regex_does_not_match_inline_text():
    """Prefix appearing in description / inline text must NOT be rewritten."""
    text = "  description: see 2026-04-18_PK-7348 for context\n"
    new, n = rmp.rewrite_session_line(text, "2026-04-18_PK-7348", "FULL")
    assert n == 0
    assert new == text


# ── four rules ────────────────────────────────────────────────────────────────

def test_R1_unique_match_rewrites(tmp_path, capsys):
    full = "2026-04-18_17-03-57-699_PK-7348-某中文標題_TXID_xxx"
    vault = _make_vault(
        tmp_path,
        sessions={full: {"transcript_path": "transcripts/x.md"}},
        wiki_files={"sources/foo.md": _wiki_with_session("2026-04-18_17-03-57-699_PK-7348")},
    )

    summary = rmp.process_vault(vault, apply=True, strict=False)
    assert summary["summary"]["rewrite"] == 1
    assert summary["summary"]["unchanged"] == 0
    assert summary["summary"]["no_match"] == 0
    assert summary["summary"]["collision"] == 0

    new = (vault / "wiki" / "sources" / "foo.md").read_text(encoding="utf-8")
    assert f"- session: {full}" in new


def test_R2_idempotent_skip(tmp_path):
    full = "2026-04-18_17-03-57-699_PK-7348-FULL"
    vault = _make_vault(
        tmp_path,
        sessions={full: {}},
        wiki_files={"sources/foo.md": _wiki_with_session(full)},
    )

    summary = rmp.process_vault(vault, apply=True, strict=False)
    assert summary["summary"]["unchanged"] == 1
    assert summary["summary"]["rewrite"] == 0
    # No backup should have been written for unchanged file
    bak_files = list((vault / "wiki" / "sources").glob("foo.md.bak.*"))
    assert bak_files == []


def test_R3_collision_fails_loud(tmp_path, capsys):
    prefix = "2026-04-18_PK-7348"
    vault = _make_vault(
        tmp_path,
        sessions={
            f"{prefix}-A": {},
            f"{prefix}-B": {},
        },
        wiki_files={"sources/foo.md": _wiki_with_session(prefix)},
    )
    with pytest.raises(SystemExit) as exc:
        rmp.process_vault(vault, apply=True, strict=False)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "collision" in err.lower()
    assert f"{prefix}-A" in err and f"{prefix}-B" in err


def test_R4_zero_match_logs_and_continues(tmp_path, capsys):
    vault = _make_vault(
        tmp_path,
        sessions={"some-other-key": {}},
        wiki_files={"sources/foo.md": _wiki_with_session("2026-04-18_PK-9999")},
    )
    summary = rmp.process_vault(vault, apply=False, strict=False)
    assert summary["summary"]["no_match"] == 1
    assert summary["summary"]["rewrite"] == 0
    err = capsys.readouterr().err
    assert "[SKIP]" in err
    assert "2026-04-18_PK-9999" in err


def test_R4_strict_fails_loud(tmp_path):
    vault = _make_vault(
        tmp_path,
        sessions={"some-other-key": {}},
        wiki_files={"sources/foo.md": _wiki_with_session("2026-04-18_PK-9999")},
    )
    with pytest.raises(SystemExit) as exc:
        rmp.process_vault(vault, apply=False, strict=True)
    assert exc.value.code == 1


# ── idempotency end-to-end ────────────────────────────────────────────────────

def test_apply_twice_no_drift(tmp_path):
    full = "2026-04-18_17-03-57-699_PK-7348-某_TXID_xxx"
    vault = _make_vault(
        tmp_path,
        sessions={full: {}},
        wiki_files={
            "sources/foo.md": _wiki_with_session("2026-04-18_17-03-57-699_PK-7348"),
        },
    )
    s1 = rmp.process_vault(vault, apply=True, strict=False)
    assert s1["summary"]["rewrite"] == 1

    after_first = (vault / "wiki" / "sources" / "foo.md").read_text(encoding="utf-8")

    # Second run: should classify as R2 (already full key) → no rewrite, no drift.
    s2 = rmp.process_vault(vault, apply=True, strict=False)
    assert s2["summary"]["rewrite"] == 0
    assert s2["summary"]["unchanged"] == 1

    after_second = (vault / "wiki" / "sources" / "foo.md").read_text(encoding="utf-8")
    assert after_first == after_second


# ── backup ────────────────────────────────────────────────────────────────────

def test_apply_creates_backup(tmp_path):
    full = "2026-04-18_PK-7348-FULL"
    vault = _make_vault(
        tmp_path,
        sessions={full: {}},
        wiki_files={"sources/foo.md": _wiki_with_session("2026-04-18_PK-7348")},
    )
    rmp.process_vault(vault, apply=True, strict=False)
    bak_files = list((vault / "wiki" / "sources").glob("foo.md.bak.*"))
    assert len(bak_files) == 1
    # backup must contain the *original* (pre-rewrite) content
    bak_text = bak_files[0].read_text(encoding="utf-8")
    assert "- session: 2026-04-18_PK-7348\n" in bak_text
    assert "FULL" not in bak_text


def test_dry_run_does_not_write(tmp_path):
    full = "2026-04-18_PK-7348-FULL"
    vault = _make_vault(
        tmp_path,
        sessions={full: {}},
        wiki_files={"sources/foo.md": _wiki_with_session("2026-04-18_PK-7348")},
    )
    summary = rmp.process_vault(vault, apply=False, strict=False)
    assert summary["summary"]["rewrite"] == 1
    # File untouched, no backup
    text = (vault / "wiki" / "sources" / "foo.md").read_text(encoding="utf-8")
    assert "- session: 2026-04-18_PK-7348\n" in text
    assert "FULL" not in text
    bak_files = list((vault / "wiki" / "sources").glob("foo.md.bak.*"))
    assert bak_files == []
