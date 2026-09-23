"""Asynchronous tailer for Antigravity JSONL transcripts and plan documents."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from ml_mon.config import AntigravityConfig
from ml_mon.core.models import StepRecord
from ml_mon.core.parser import ConversationParser


class ConversationTailer:
    """Tails an active conversation's transcript log and planning documents."""

    def __init__(self, conversation_id: str, config: Optional[AntigravityConfig] = None):
        self.conversation_id = conversation_id
        self.config = config or AntigravityConfig.discover()
        self.parser = ConversationParser(self.config)
        self._last_offset = 0
        self._last_plan_hash = ""

    async def stream_events(self, poll_interval: float = 0.5) -> AsyncGenerator[dict, None]:
        """Stream new step records and plan updates as they are written."""
        transcript_path = self.config.get_transcript_path(self.conversation_id)

        # Initialize offset to end if needed, or start from 0 to emit history first
        # Here we emit from start of file so client receives all events
        self._last_offset = 0

        while True:
            # 1. Check for new transcript lines
            if transcript_path and transcript_path.exists():
                try:
                    file_size = transcript_path.stat().st_size
                    if file_size > self._last_offset:
                        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(self._last_offset)
                            for line in f:
                                line_str = line.strip()
                                if line_str:
                                    try:
                                        record = json.loads(line_str)
                                        step = self.parser.parse_step_record(record)
                                        yield {
                                            "event": "step",
                                            "data": step.model_dump(),
                                        }
                                    except Exception:
                                        pass
                            self._last_offset = f.tell()
                except Exception:
                    pass
            else:
                # If transcript not yet created, re-check path
                transcript_path = self.config.get_transcript_path(self.conversation_id)

            # 2. Check for plan updates
            plan_path = self.config.get_plan_path(self.conversation_id)
            if plan_path and plan_path.exists():
                try:
                    mtime = plan_path.stat().st_mtime
                    content = plan_path.read_text(encoding="utf-8", errors="ignore")
                    content_hash = f"{mtime}_{len(content)}"
                    if content_hash != self._last_plan_hash:
                        self._last_plan_hash = content_hash
                        plan_asset = self.parser.parse_plan_asset(self.conversation_id)
                        if plan_asset:
                            yield {
                                "event": "plan",
                                "data": plan_asset.model_dump(),
                            }
                except Exception:
                    pass

            await asyncio.sleep(poll_interval)
