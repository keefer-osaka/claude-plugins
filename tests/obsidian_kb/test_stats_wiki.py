import sys
import os

_base = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/kb-stats/scripts'))
sys.path.insert(0, os.path.join(_base, '../../plugins/obsidian-kb/vault-payload/.claude/skills/_lib'))

from datetime import date

import pytest

import stats_wiki as sw


def _make_page(**kw):
    base = {
        "path": "wiki/foo.md",
        "type": "concept",
        "status": "draft",
        "confidence": "medium",
        "updated": date(2026, 1, 1),
        "has_tldr": True,
        "source_count": 1,
        "source_blocks": [{"session": "s1", "has_transcript": True}],
    }
    base.update(kw)
    return base


class TestPct:
    def test_zero_n(self):
        assert sw.pct(0, 10) == "0%"

    def test_zero_total(self):
        assert sw.pct(5, 0) == "0%"

    def test_quarter(self):
        assert sw.pct(1, 4) == "25%"

    def test_full(self):
        assert sw.pct(10, 10) == "100%"


class TestBar:
    def test_zero_total(self):
        out = sw.bar(5, 0, width=10)
        assert out == " " * 10

    def test_full(self):
        out = sw.bar(10, 10, width=10)
        assert out == "█" * 10

    def test_proportional(self):
        out = sw.bar(5, 10, width=10)
        assert out.count("█") == 5
        assert out.count("░") == 5


class TestComputeStats:
    def test_type_counts(self):
        pages = [_make_page(type="entity"), _make_page(type="concept"),
                 _make_page(type="concept")]
        d = sw.compute_stats(pages)
        assert d["types"]["concept"] == 2
        assert d["types"]["entity"] == 1

    def test_status_counts(self):
        pages = [_make_page(status="draft"), _make_page(status="verified")]
        d = sw.compute_stats(pages)
        assert d["statuses"]["draft"] == 1
        assert d["statuses"]["verified"] == 1

    def test_tldr_count(self):
        pages = [_make_page(has_tldr=True), _make_page(has_tldr=False)]
        d = sw.compute_stats(pages)
        assert d["tldr_count"] == 1

    def test_source_coverage(self):
        pages = [_make_page(source_count=2), _make_page(source_count=0)]
        d = sw.compute_stats(pages)
        assert d["has_source"] == 1
        assert d["total_source_refs"] == 2
        assert d["avg_sources"] == 1.0

    def test_transcript_linked(self):
        pages = [
            _make_page(source_blocks=[
                {"session": "s1", "has_transcript": True},
                {"session": "s2", "has_transcript": False},
            ], path="a.md"),
        ]
        d = sw.compute_stats(pages)
        assert d["transcript_linked"] == 1
        # no manifest → unlinked sources all classified as broken_sources
        assert len(d["broken_sources"]) == 1
        assert d["broken_sources"][0] == ("a.md", "s2")

    def test_freshness_buckets(self, monkeypatch):
        monkeypatch.setattr(sw, "TODAY", date(2026, 4, 1))
        pages = [
            _make_page(updated=date(2026, 3, 15)),   # 17d → in 30/60/90
            _make_page(updated=date(2026, 2, 15)),   # 45d → in 60/90
            _make_page(updated=date(2026, 1, 1)),    # 90d → in 90
            _make_page(updated=date(2025, 10, 1)),   # 182d → out
        ]
        d = sw.compute_stats(pages)
        assert d["fresh_30"] == 1
        assert d["fresh_60"] == 2
        assert d["fresh_90"] == 3

    def test_oldest_page(self, monkeypatch):
        monkeypatch.setattr(sw, "TODAY", date(2026, 4, 1))
        pages = [
            _make_page(path="new.md", updated=date(2026, 3, 1)),
            _make_page(path="old.md", updated=date(2025, 1, 1)),
        ]
        d = sw.compute_stats(pages)
        assert d["oldest"][0] == "old.md"

    def test_no_updated_counted(self):
        pages = [_make_page(updated=None), _make_page(updated=date(2026, 1, 1))]
        d = sw.compute_stats(pages)
        assert d["no_updated_field"] == 1

    def test_empty(self):
        d = sw.compute_stats([])
        assert d["total"] == 0
        assert d["avg_sources"] == 0
        assert d["oldest"] is None


class TestRenderReport:
    def test_all_sections(self):
        stats = sw.compute_stats([_make_page()])
        ts = {"transcripts": 1, "sessions": 1, "orphan_files": [], "missing_files": []}
        out = sw.render_report(stats, ts)
        for heading in ["1. 頁面分佈", "2. 狀態分佈", "3. 信心度分佈",
                        "4. TL;DR 覆蓋率", "5. 來源覆蓋率", "6. Transcript 連結率",
                        "7. 新鮮度", "8. Transcripts 層"]:
            assert heading in out

    def test_orphan_listed(self):
        stats = sw.compute_stats([_make_page()])
        ts = {"transcripts": 2, "sessions": 1,
              "orphan_files": ["dangling.md"], "missing_files": []}
        out = sw.render_report(stats, ts)
        assert "dangling.md" in out

    def test_missing_listed(self):
        stats = sw.compute_stats([_make_page()])
        ts = {"transcripts": 1, "sessions": 2,
              "orphan_files": [], "missing_files": ["gone.md"]}
        out = sw.render_report(stats, ts)
        assert "gone.md" in out


# ── TestLoadTranscriptsStats ──────────────────────────────────────────────────

class TestLoadTranscriptsStats:
    def test_missing_dirs_return_zeros(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sw, "TRANSCRIPTS_DIR", tmp_path / "nonexistent")
        monkeypatch.setattr(sw, "SESSIONS_JSON_PATH", tmp_path / "nonexistent.json")
        result = sw.load_transcripts_stats()
        assert result["transcripts"] == 0
        assert result["sessions"] == 0
        assert result["orphan_files"] == []
        assert result["missing_files"] == []

    def test_transcript_files_counted(self, monkeypatch, tmp_path):
        trans = tmp_path / "transcripts"
        trans.mkdir()
        (trans / "a.md").write_text("")
        (trans / "b.md").write_text("")
        (trans / "_index.md").write_text("")
        monkeypatch.setattr(sw, "TRANSCRIPTS_DIR", trans)
        monkeypatch.setattr(sw, "SESSIONS_JSON_PATH", tmp_path / "nonexistent.json")
        assert sw.load_transcripts_stats()["transcripts"] == 2

    def test_sessions_json_counted(self, monkeypatch, tmp_path):
        trans = tmp_path / "transcripts"
        trans.mkdir()
        sj = tmp_path / "sessions.json"
        sj.write_text('{"s1": {"transcript_path": "transcripts/a.md"}, "s2": {}}')
        monkeypatch.setattr(sw, "TRANSCRIPTS_DIR", trans)
        monkeypatch.setattr(sw, "SESSIONS_JSON_PATH", sj)
        assert sw.load_transcripts_stats()["sessions"] == 2

    def test_corrupted_json_does_not_raise(self, monkeypatch, tmp_path):
        trans = tmp_path / "transcripts"
        trans.mkdir()
        sj = tmp_path / "sessions.json"
        sj.write_text("{bad json}")
        monkeypatch.setattr(sw, "TRANSCRIPTS_DIR", trans)
        monkeypatch.setattr(sw, "SESSIONS_JSON_PATH", sj)
        result = sw.load_transcripts_stats()
        assert result["sessions"] == 0

    def test_orphan_files_detected(self, monkeypatch, tmp_path):
        trans = tmp_path / "transcripts"
        trans.mkdir()
        (trans / "orphan.md").write_text("")
        sj = tmp_path / "sessions.json"
        sj.write_text('{"s1": {"transcript_path": "transcripts/other.md"}}')
        monkeypatch.setattr(sw, "TRANSCRIPTS_DIR", trans)
        monkeypatch.setattr(sw, "SESSIONS_JSON_PATH", sj)
        assert "orphan.md" in sw.load_transcripts_stats()["orphan_files"]

    def test_missing_files_detected(self, monkeypatch, tmp_path):
        trans = tmp_path / "transcripts"
        trans.mkdir()
        sj = tmp_path / "sessions.json"
        sj.write_text('{"s1": {"transcript_path": "transcripts/missing.md"}}')
        monkeypatch.setattr(sw, "TRANSCRIPTS_DIR", trans)
        monkeypatch.setattr(sw, "SESSIONS_JSON_PATH", sj)
        assert "missing.md" in sw.load_transcripts_stats()["missing_files"]
