#!/usr/bin/env python3
"""Post-import repair wrapper (fuse pattern: never abort /kb-import).

Runs three idempotent repair scripts in fixed order, classifies each by
exit code into structured status, and always exits 0 to honor Principle 2.
Output: one JSON line on stdout for SKILL agent to ingest.

Usage:
    python3 post_import_repair.py <vault_dir>
    python3 post_import_repair.py  # uses cwd as vault_dir
"""
import json
import subprocess
import sys
from pathlib import Path


def classify_repair(returncode: int) -> str:
    """repair_filename_mojibake.py exit codes:
       0 = ok, 2 = nothing-to-do (skip-if-clean),
       3 = TZ-not-normalized, 4 = cross-author-conflict,
       other non-zero = fatal."""
    if returncode == 0:
        return "ok"
    if returncode == 2:
        return "skipped"
    if returncode == 3:
        return "warn:tz_not_normalized"
    if returncode == 4:
        return "warn:cross_author_conflict"
    return f"warn:exit_{returncode}"


def classify_simple(returncode: int) -> str:
    """remap_wiki_session_prefix.py / backfill_wiki_links.py:
       0 = ok, non-zero = warn (no special codes)."""
    return "ok" if returncode == 0 else f"warn:exit_{returncode}"


def main() -> int:
    vault_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    scripts_dir = vault_dir / ".claude" / "skills" / "kb-ingest" / "scripts"
    manifest = vault_dir / "_schema" / "repair_manifest.json"
    status: dict[str, str] = {}

    # --- Step 1: repair_filename_mojibake.py ---------------------------------
    # Manifest residue handling: if manifest exists from prior cross-author
    # conflict (exit 4), do NOT auto-resume. Surface a WARN and skip step 1
    # to honor Principle 2 (fuse: never abort import).
    skip_repair = False
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            last_exit = data.get("last_exit_code")
            if last_exit == 4:
                print(
                    "[WARN] _schema/repair_manifest.json exists from prior "
                    "cross-author conflict; run repair manually with --resume "
                    "after resolving",
                    file=sys.stderr,
                )
                status["repair"] = "warn:manifest_residue_conflict"
                skip_repair = True
        except (OSError, json.JSONDecodeError):
            # Corrupt manifest -> still attempt --resume
            pass

    if not skip_repair:
        cmd = [
            sys.executable,
            str(scripts_dir / "repair_filename_mojibake.py"),
            "--apply",
            "--include-content",
            "--skip-if-clean",
        ]
        if manifest.exists():
            cmd.append("--resume")
        r = subprocess.run(cmd, cwd=vault_dir)
        status["repair"] = classify_repair(r.returncode)

    # --- Step 2 & 3: always run (stateless, no manifest, no noise) ----------
    # Continue regardless of step 1 outcome (fuse: never abort).
    for name, script in [
        ("remap", "remap_wiki_session_prefix.py"),
        ("backfill", "backfill_wiki_links.py"),
    ]:
        r2 = subprocess.run(
            [sys.executable, str(scripts_dir / script), "--apply"],
            cwd=vault_dir,
        )
        status[name] = classify_simple(r2.returncode)

    # --- Emit single JSON line for SKILL agent to capture -------------------
    print(json.dumps({"post_import_repair": status}))
    return 0  # Always 0: fuse never aborts /kb-import


if __name__ == "__main__":
    sys.exit(main())
