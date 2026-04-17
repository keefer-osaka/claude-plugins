#!/usr/bin/env python3
"""
更新 --all 模式的游標 .all_watermark。
用法：python3 update_all_watermark.py <max_mtime>
其中 max_mtime 是本批次最大的檔案 mtime（Unix timestamp，從 scan_sessions.py 的 max_candidate_mtime 取得）。
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")))
from wiki_utils import resolve_vault_dir

VAULT_DIR = resolve_vault_dir(__file__)
ALL_WATERMARK_PATH = os.path.join(VAULT_DIR, "_schema", ".all_watermark")

if len(sys.argv) < 2:
    print("用法：python3 update_all_watermark.py <max_mtime>", file=sys.stderr)
    sys.exit(1)

try:
    max_mtime = float(sys.argv[1])
except ValueError:
    print(f"錯誤：無效的 mtime 值：{sys.argv[1]}", file=sys.stderr)
    sys.exit(1)

with open(ALL_WATERMARK_PATH, "w", encoding="utf-8") as f:
    f.write(str(max_mtime) + "\n")

dt = datetime.fromtimestamp(max_mtime, tz=timezone.utc).isoformat()
print(f"all_watermark 已更新至：{dt}（mtime: {max_mtime}）")
