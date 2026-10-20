#!/usr/bin/env python3
"""Private output files for the MVQ grader, with the exporter's permission rules (Vault, PR #57).

Every target is checked BEFORE anything is written, and again after:
  * never inside a git worktree (repo, worktree `.git` file, or a symlink into one);
  * an existing target file must be a regular 0600 file (no symlink, nothing looser);
  * the target folder and every existing parent we own must be 0700 (setgid 2770, 0755,
    0750 ... are refused). Walking stops at a folder owned by someone else, at $HOME,
    at $HERMES_HOME (the box data root, e.g. /opt/data) and at /.
  * missing folders are created one by one as 0700; an existing folder is never chmod'ed.
Refusals raise OutputRefused with a short reason and a path count, never file content.

Retention: every file written here gets an entry in a retention manifest (0600) with a
deletion date RETENTION_DAYS after creation.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

RETENTION_DAYS = 30
MANIFEST_NAME = "retention-manifest.json"


class OutputRefused(RuntimeError):
    pass


def inside_git_worktree(path: Path) -> bool:
    p = Path(path).resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return True
    return False


def _stop_dirs() -> set[Path]:
    stops = {Path("/")}
    for env in ("HOME", "HERMES_HOME"):
        v = os.environ.get(env)
        if v:
            stops.add(Path(v).resolve())
    stops.add(Path(tempfile.gettempdir()).resolve())
    return stops


def loose_dirs(folder: Path) -> list[Path]:
    """Existing folders from `folder` upward that we own and that are looser than 0700."""
    bad: list[Path] = []
    stops = _stop_dirs()
    uid = os.getuid()
    p = Path(folder).absolute()
    while not p.exists():
        if p.parent == p:
            return bad
        p = p.parent
    p = p.resolve()
    for d in [p, *p.parents]:
        if d in stops:
            break
        st = os.stat(d)
        if st.st_uid != uid:
            break
        if (st.st_mode & 0o777) & ~0o700 or st.st_mode & stat.S_ISGID:
            bad.append(d)
    return bad


def check_target(path: Path) -> None:
    """Raise OutputRefused unless `path` may be written privately (see module doc). No writes."""
    path = Path(path)
    if inside_git_worktree(path):
        raise OutputRefused("inside_git_worktree")
    if path.is_symlink():
        raise OutputRefused("target_is_symlink")
    if path.exists():
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            raise OutputRefused("target_not_regular_file")
        if (st.st_mode & 0o777) & ~0o600:
            raise OutputRefused("loose_permissions paths=1")
    bad = loose_dirs(path.parent)
    if bad:
        raise OutputRefused(f"loose_permissions paths={len(bad)}")


def check_targets(paths: list[Path]) -> None:
    for p in paths:
        check_target(p)


def ensure_private_dir(folder: Path) -> None:
    """Create missing folders one at a time as 0700. Existing folders are checked, never chmod'ed."""
    folder = Path(folder).absolute()
    missing: list[Path] = []
    p = folder
    while not p.exists():
        missing.append(p)
        p = p.parent
    old = os.umask(0o077)
    try:
        for d in reversed(missing):
            d.mkdir(mode=0o700)
    finally:
        os.umask(old)
    bad = loose_dirs(folder)
    if bad:
        raise OutputRefused(f"loose_permissions paths={len(bad)}")


def write_private(path: Path, text: str) -> None:
    """Check, then write atomically as a new 0600 file (temp file + rename), then re-check."""
    path = Path(path)
    check_target(path)
    ensure_private_dir(path.parent)
    old = os.umask(0o077)
    try:
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                h.write(text)
                h.flush()
                os.fsync(h.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    finally:
        os.umask(old)
    st = os.lstat(path)
    if (st.st_mode & 0o777) != 0o600 or loose_dirs(path.parent):
        shred_file(path)
        raise OutputRefused("loose_permissions_after_write")


def shred_file(path: Path) -> bool:
    """Overwrite with zeros, fsync, unlink. Returns True when the path is gone afterwards."""
    path = Path(path)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return True
    if stat.S_ISREG(st.st_mode) and st.st_size:
        with open(path, "r+b", buffering=0) as h:
            remaining = st.st_size
            while remaining > 0:
                n = min(remaining, 1 << 20)
                h.write(b"\0" * n)
                remaining -= n
            os.fsync(h.fileno())
    path.unlink(missing_ok=True)
    return not path.exists() and not path.is_symlink()


def deletion_date(created: datetime | None = None) -> str:
    created = created or datetime.now(timezone.utc)
    return (created + timedelta(days=RETENTION_DAYS)).date().isoformat()


def record_retention(manifest: Path, entries: list[dict]) -> None:
    """Add or update entries (keyed by path) in a 0600 retention manifest beside the outputs.

    Each entry: path, kind, created_at, deletion_date (created + 30 days), status (kept|shredded).
    Paths and dates only, never content.
    """
    manifest = Path(manifest)
    data = {"retention_days": RETENTION_DAYS, "files": []}
    if manifest.exists():
        check_target(manifest)
        data = json.loads(manifest.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    by_path = {f["path"]: f for f in data.get("files", [])}
    for e in entries:
        row = by_path.get(str(e["path"]), {})
        created = row.get("created_at") or now.isoformat()
        row.update({
            "path": str(e["path"]),
            "kind": e.get("kind", row.get("kind", "")),
            "created_at": created,
            "deletion_date": row.get("deletion_date") or deletion_date(datetime.fromisoformat(created)),
            "status": e.get("status", row.get("status", "kept")),
        })
        if e.get("status") == "shredded":
            row["shredded_at"] = now.isoformat()
        by_path[row["path"]] = row
    data["files"] = list(by_path.values())
    write_private(manifest, json.dumps(data, indent=2) + "\n")
