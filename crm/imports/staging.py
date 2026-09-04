"""Holds an uploaded CSV on disk between the preview and the confirm step.

The upload is re-parsed at confirm time rather than the parse result being
serialised, so what gets written is always what the preview described.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path

from bridge_crm.config import get_settings

logger = logging.getLogger(__name__)

STAGING_TTL_SECONDS = 6 * 3600


def _staging_dir() -> Path:
    path = Path(get_settings().import_staging_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _staging_path(token: str) -> Path | None:
    if not token or not token.isalnum() or len(token) > 64:
        return None
    return _staging_dir() / f"{token}.json"


def stage_upload(*, content: str, filename: str, user_id: int) -> str:
    prune_expired()
    token = secrets.token_hex(16)
    path = _staging_dir() / f"{token}.json"
    path.write_text(
        json.dumps(
            {
                "user_id": int(user_id),
                "filename": filename,
                "created_at": time.time(),
                "content": content,
            }
        ),
        encoding="utf-8",
    )
    return token


def load_upload(token: str, *, user_id: int) -> dict | None:
    path = _staging_path(token)
    if path is None or not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable import staging file %s", token)
        return None

    if int(record.get("user_id", -1)) != int(user_id):
        return None
    if time.time() - float(record.get("created_at", 0)) > STAGING_TTL_SECONDS:
        discard_upload(token)
        return None
    return record


def discard_upload(token: str) -> None:
    path = _staging_path(token)
    if path is not None:
        path.unlink(missing_ok=True)


def prune_expired() -> None:
    cutoff = time.time() - STAGING_TTL_SECONDS
    try:
        for path in _staging_dir().glob("*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not prune import staging directory", exc_info=True)
