#!/usr/bin/env python3
"""更新水位線到當前時間。"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")))
from wiki_utils import resolve_vault_dir

VAULT_DIR = resolve_vault_dir(__file__)
WATERMARK_PATH = os.path.join(VAULT_DIR, "_schema", ".watermark")

now = datetime.now(timezone.utc).isoformat()
with open(WATERMARK_PATH, "w", encoding="utf-8") as f:
    f.write(now + "\n")
print(f"水位線已更新至：{now}")
