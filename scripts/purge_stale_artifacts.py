#!/usr/bin/env python3
"""Data Retention & Artifact Cleanup Script

Scans runtime directories for completed jobs, processed outputs, staging files,
and dead-letter payloads older than a configured retention TTL and safely purges them.

Usage:
    python scripts/purge_stale_artifacts.py --dry-run
    python scripts/purge_stale_artifacts.py --max-age-days 14 --staging-max-age-days 7
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("purge_stale_artifacts")


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


def _format_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def purge_stale_entries(
    target_dir: Path,
    max_age_days: float,
    *,
    dry_run: bool = False,
    is_file_only: bool = False,
) -> tuple[int, int]:
    """Purge subdirectories or files in target_dir older than max_age_days.

    Returns (count_purged, total_bytes_freed).
    """
    if not target_dir.exists():
        return 0, 0

    now = time.time()
    cutoff_seconds = max_age_days * 86400.0
    purged_count = 0
    bytes_freed = 0

    entries = list(target_dir.iterdir())
    for entry in entries:
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue

        age_seconds = now - mtime
        if age_seconds >= cutoff_seconds:
            size = _dir_size(entry)
            age_days = age_seconds / 86400.0
            if dry_run:
                log.info(
                    "[DRY-RUN] Would purge: %s (age: %.1f days, size: %s)",
                    entry,
                    age_days,
                    _format_size(size),
                )
            else:
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
                    log.info(
                        "Purged: %s (age: %.1f days, size: %s)",
                        entry,
                        age_days,
                        _format_size(size),
                    )
                except Exception as e:
                    log.error("Failed to purge %s: %s", entry, e)
                    continue
            purged_count += 1
            bytes_freed += size

    return purged_count, bytes_freed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purge stale jobs, processed artifacts, and staging files based on retention policy."
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("DATA_DIR", "data"),
        help="Base data directory (default: 'data' or $DATA_DIR)",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=float(os.getenv("RETENTION_MAX_AGE_DAYS", "14.0")),
        help="Retention period in days for jobs and processed artifacts (default: 14.0)",
    )
    parser.add_argument(
        "--staging-max-age-days",
        type=float,
        default=float(os.getenv("STAGING_MAX_AGE_DAYS", "7.0")),
        help="Retention period in days for temporary staging files (default: 7.0)",
    )
    parser.add_argument(
        "--include-dead-letter",
        action="store_true",
        default=False,
        help="Also purge records in dead_letter directory older than max-age-days",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be deleted without actually deleting",
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir).resolve()
    log.info(
        "Starting artifact retention scan (data_dir=%s, max_age=%.1f days, dry_run=%s)",
        data_dir,
        args.max_age_days,
        args.dry_run,
    )

    total_purged = 0
    total_bytes = 0

    targets = [
        (data_dir / "processed", args.max_age_days, False),
        (data_dir / "jobs", args.max_age_days, False),
        (data_dir / "staging", args.staging_max_age_days, False),
        (data_dir / "idempotency", args.max_age_days, True),
    ]

    if args.include_dead_letter:
        targets.append((data_dir / "dead_letter", args.max_age_days, True))

    for target_dir, max_age, is_file_only in targets:
        if target_dir.exists():
            count, b_freed = purge_stale_entries(
                target_dir, max_age, dry_run=args.dry_run, is_file_only=is_file_only
            )
            total_purged += count
            total_bytes += b_freed

    action_label = "Would free" if args.dry_run else "Freed"
    log.info(
        "Retention scan complete. %s %s across %d items.",
        action_label,
        _format_size(total_bytes),
        total_purged,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
