"""Discovers and scans Antigravity conversations across SQLite and brain folders."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ml_mon.config import AntigravityConfig
from ml_mon.core.models import ConversationSummary


class ConversationScanner:
    """Discovers conversations, reads metadata, and tracks active status."""

    def __init__(self, config: Optional[AntigravityConfig] = None):
        self.config = config or AntigravityConfig.discover()

    def list_conversation_ids(self) -> list[str]:
        """Find all unique conversation IDs across conversations/ and brain/ directories."""
        ids: set[str] = set()

        # 1. Search SQLite databases in conversations/
        if self.config.conversations_dir.exists():
            for p in self.config.conversations_dir.glob("*.db"):
                if p.is_file() and not p.name.endswith(("-wal", "-shm")):
                    ids.add(p.stem)

        # 2. Search brain directories
        if self.config.brain_dir.exists():
            for p in self.config.brain_dir.iterdir():
                if p.is_dir() and not p.name.startswith("."):
                    ids.add(p.name)

        return list(ids)

    def scan_all(self) -> list[ConversationSummary]:
        """Scan all conversations and return summaries sorted by last activity."""
        summaries: list[ConversationSummary] = []
        for conv_id in self.list_conversation_ids():
            summary = self.get_summary(conv_id)
            if summary:
                summaries.append(summary)

        # Sort newest first based on last_modified
        summaries.sort(
            key=lambda s: s.last_modified or s.created_at or "",
            reverse=True,
        )
        return summaries

    def get_summary(self, conversation_id: str) -> Optional[ConversationSummary]:
        """Extract summary metadata for a single conversation ID."""
        db_path = self.config.get_conversation_db(conversation_id)
        brain_path = self.config.get_brain_dir(conversation_id)
        transcript_path = self.config.get_transcript_path(conversation_id)
        plan_path = self.config.get_plan_path(conversation_id)
        walkthrough_path = self.config.get_walkthrough_path(conversation_id)

        has_sqlite = db_path.exists()
        has_transcript = transcript_path is not None and transcript_path.exists()

        if not has_sqlite and not brain_path.exists():
            return None

        # Determine timestamps
        mtimes: list[float] = []
        ctimes: list[float] = []

        if has_sqlite:
            st = db_path.stat()
            mtimes.append(st.st_mtime)
            ctimes.append(st.st_ctime)
            # Check wal file
            wal_path = self.config.conversations_dir / f"{conversation_id}.db-wal"
            if wal_path.exists():
                mtimes.append(wal_path.stat().st_mtime)

        if has_transcript and transcript_path:
            st = transcript_path.stat()
            mtimes.append(st.st_mtime)
            ctimes.append(st.st_ctime)

        if plan_path and plan_path.exists():
            mtimes.append(plan_path.stat().st_mtime)

        last_mtime = max(mtimes) if mtimes else 0.0
        first_ctime = min(ctimes) if ctimes else last_mtime

        last_modified_str = datetime.fromtimestamp(last_mtime).isoformat() if last_mtime else None
        created_at_str = datetime.fromtimestamp(first_ctime).isoformat() if first_ctime else None

        # Determine step count
        step_count = self._get_step_count(db_path, transcript_path)

        # Extract title
        title = self._extract_title(transcript_path, db_path) or f"Session {conversation_id[:8]}"

        # Is active if modified in the last 2 minutes
        is_active = (time.time() - last_mtime) < 120 if last_mtime else False

        return ConversationSummary(
            id=conversation_id,
            title=title,
            created_at=created_at_str,
            last_modified=last_modified_str,
            step_count=step_count,
            is_active=is_active,
            has_plan=plan_path is not None,
            has_walkthrough=walkthrough_path is not None,
            has_sqlite=has_sqlite,
            has_transcript=has_transcript,
        )

    def _get_step_count(self, db_path: Path, transcript_path: Optional[Path]) -> int:
        """Count steps from SQLite or transcript log."""
        if db_path.exists():
            try:
                uri = f"file:{db_path}?mode=ro"
                with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM steps")
                    row = cur.fetchone()
                    if row:
                        return int(row[0])
            except Exception:
                pass

        if transcript_path and transcript_path.exists():
            try:
                count = 0
                with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                    for _ in f:
                        count += 1
                return count
            except Exception:
                pass

        return 0

    def _extract_title(self, transcript_path: Optional[Path], db_path: Path) -> Optional[str]:
        """Extract conversation title from initial user prompt."""
        if transcript_path and transcript_path.exists():
            try:
                with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        if record.get("type") == "USER_INPUT":
                            content = record.get("content", "")
                            # Look for <USER_REQUEST> ... </USER_REQUEST>
                            match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                            req_text = match.group(1).strip() if match else content.strip()
                            # Take first meaningful non-empty line
                            for l in req_text.splitlines():
                                l_clean = l.strip("#* \t\r\n")
                                if l_clean and len(l_clean) > 3:
                                    return l_clean[:80]
                            break
            except Exception:
                pass

        return None
