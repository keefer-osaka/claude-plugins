## mojibake repair 三件組（暫時保險絲）

`repair_filename_mojibake.py` / `remap_wiki_session_prefix.py` /
`backfill_wiki_links.py` 透過 `post_import_repair.py` wrapper 由
`kb-import/SKILL.md`「修復跨平台 mojibake」章節呼叫。

### 移除條件

當以下三項全部成立後，刪除：

1. `scan_markdown.py` 改用 utf-8 解 zip（不再產生 cp437 mojibake session_id）。
2. 通過至少 3 個跨平台 contributor zip 的回歸驗證。
3. 至少一個 release cycle 內 `post_import_repair.py` 觀察到 `repair: skipped` 為穩定常態。

### 移除步驟

1. 刪除 `kb-import/SKILL.md` 的「修復跨平台 mojibake」章節與完成回報第 5 項。
2. 刪除 `post_import_repair.py`。
3. 三腳本（repair / remap / backfill）可保留供 ad-hoc 修補，但移除 `--skip-if-clean` flag。
