import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../plugins/obsidian-kb/vault-payload/.claude/skills/_lib'))

import re
from datetime import timezone, timedelta
from wiki_utils import (
    resolve_vault_dir,
    parse_frontmatter,
    WIKILINK_RE,
    TW_TZ,
    VAULT_TZ,
    VAULT_TZ_OFFSET,
    format_tw_date,
    extract_fm_text,
    find_duplicate_top_level_keys,
    parse_source_blocks,
    collect_content_pages,
    TOP_LEVEL_SKIP,
)


# ── TW_TZ ────────────────────────────────────────────────────────────────────

def test_tw_tz_is_utc8():
    # TW_TZ is a backward-compat alias for VAULT_TZ; offset comes from env/config
    assert TW_TZ == timezone(timedelta(hours=VAULT_TZ_OFFSET))
    assert TW_TZ is VAULT_TZ


# ── WIKILINK_RE ───────────────────────────────────────────────────────────────

def test_wikilink_re_matches_basic():
    assert WIKILINK_RE.findall("see [[Topic A]] and [[Topic B]]") == ["Topic A", "Topic B"]

def test_wikilink_re_no_match():
    assert WIKILINK_RE.findall("no links here") == []


# ── resolve_vault_dir ─────────────────────────────────────────────────────────

def test_resolve_vault_dir():
    fake_script = "/vault/.claude/skills/my-skill/scripts/run.py"
    result = resolve_vault_dir(fake_script)
    assert result == "/vault"


# ── parse_frontmatter ─────────────────────────────────────────────────────────

def test_parse_frontmatter_no_frontmatter():
    fm, body = parse_frontmatter("just body text")
    assert fm == {}
    assert body == "just body text"

def test_parse_frontmatter_basic():
    text = "---\ntitle: Hello\nauthor: World\n---\nbody here"
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "Hello"
    assert fm["author"] == "World"
    assert body == "body here"

def test_parse_frontmatter_inline_list():
    text = "---\ntags: [a, b, c]\n---\nbody"
    fm, body = parse_frontmatter(text)
    assert fm["tags"] == ["a", "b", "c"]

def test_parse_frontmatter_multiline_list():
    text = "---\ntags:\n  - alpha\n  - beta\n---\nbody"
    fm, body = parse_frontmatter(text)
    assert fm["tags"] == ["alpha", "beta"]

def test_parse_frontmatter_missing_closing():
    text = "---\ntitle: Oops\nbody text"
    fm, body = parse_frontmatter(text)
    assert fm == {}

def test_parse_frontmatter_quoted_value():
    text = '---\ntitle: "Quoted Title"\n---\n'
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "Quoted Title"


# ── format_tw_date ────────────────────────────────────────────────────────────

def test_format_tw_date_utc_z():
    # 2024-01-01T16:00:00Z → 2024-01-02 in UTC+8
    result = format_tw_date("2024-01-01T16:00:00Z")
    assert result == "2024-01-02"

def test_format_tw_date_already_date():
    result = format_tw_date("2024-06-15T00:00:00+08:00")
    assert result == "2024-06-15"

def test_format_tw_date_fallback_short():
    # "not-a-date" is exactly 10 chars, so fallback returns it as-is
    result = format_tw_date("not-a-date")
    assert result == "not-a-date"

def test_format_tw_date_empty():
    result = format_tw_date("")
    assert result == ""


# ── extract_fm_text ───────────────────────────────────────────────────────────

def test_extract_fm_text_basic():
    text = "---\ntitle: Hi\n---\nbody"
    assert extract_fm_text(text) == "title: Hi"

def test_extract_fm_text_no_frontmatter():
    assert extract_fm_text("no fm") == ""

def test_extract_fm_text_missing_closing():
    assert extract_fm_text("---\ntitle: Hi") == ""


# ── find_duplicate_top_level_keys ─────────────────────────────────────────────

def test_find_duplicate_top_level_keys_none():
    fm_text = "title: A\nauthor: B"
    assert find_duplicate_top_level_keys(fm_text) == []

def test_find_duplicate_top_level_keys_found():
    fm_text = "title: A\nauthor: B\ntitle: C"
    assert find_duplicate_top_level_keys(fm_text) == ["title"]

def test_find_duplicate_top_level_keys_ignores_indented():
    fm_text = "sources:\n  - session: abc\n  - session: def"
    assert find_duplicate_top_level_keys(fm_text) == []


# ── parse_source_blocks ───────────────────────────────────────────────────────

def test_parse_source_blocks_empty():
    assert parse_source_blocks("title: A") == []

def test_parse_source_blocks_single_no_transcript():
    fm_text = "sources:\n  - session: abc123"
    blocks = parse_source_blocks(fm_text)
    assert len(blocks) == 1
    assert blocks[0]["session"] == "abc123"
    assert blocks[0]["has_transcript"] is False

def test_parse_source_blocks_with_transcript():
    fm_text = "sources:\n  - session: abc123\n    transcript: yes"
    blocks = parse_source_blocks(fm_text)
    assert blocks[0]["has_transcript"] is True

def test_parse_source_blocks_multiple():
    fm_text = "sources:\n  - session: s1\n  - session: s2\n    transcript: yes"
    blocks = parse_source_blocks(fm_text)
    assert len(blocks) == 2
    assert blocks[0]["session"] == "s1"
    assert blocks[1]["session"] == "s2"
    assert blocks[1]["has_transcript"] is True


# ── collect_content_pages ─────────────────────────────────────────────────────

def test_collect_content_pages_empty_dir(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    pages = collect_content_pages(str(wiki_dir))
    assert pages == []

def test_collect_content_pages_skips_top_level_files(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    for name in TOP_LEVEL_SKIP:
        (wiki_dir / name).write_text("---\ntitle: skip\n---\nbody")
    pages = collect_content_pages(str(wiki_dir))
    assert pages == []

def test_collect_content_pages_skips_meta_dir(tmp_path):
    wiki_dir = tmp_path / "wiki"
    meta_dir = wiki_dir / "meta"
    meta_dir.mkdir(parents=True)
    (meta_dir / "stats.md").write_text("---\ntitle: meta\n---\nbody")
    pages = collect_content_pages(str(wiki_dir))
    assert pages == []

def test_collect_content_pages_basic_page(tmp_path):
    wiki_dir = tmp_path / "wiki"
    topic_dir = wiki_dir / "topic"
    topic_dir.mkdir(parents=True)
    content = "---\ntype: concept\nstatus: published\n---\n## TL;DR\nsome summary"
    (topic_dir / "page.md").write_text(content)
    pages = collect_content_pages(str(wiki_dir))
    assert len(pages) == 1
    p = pages[0]
    assert p["type"] == "concept"
    assert p["status"] == "published"
    assert p["has_tldr"] is True

def test_collect_content_pages_skips_index(tmp_path):
    wiki_dir = tmp_path / "wiki"
    sub = wiki_dir / "sub"
    sub.mkdir(parents=True)
    (sub / "_index.md").write_text("---\ntitle: index\n---\nbody")
    pages = collect_content_pages(str(wiki_dir))
    assert pages == []
