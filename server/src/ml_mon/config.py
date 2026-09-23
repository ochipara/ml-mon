"""Configuration and path discovery for Antigravity IDE storage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class AntigravityConfig(BaseModel):
    """Configuration resolving Antigravity storage directories."""

    base_dir: Path = Field(description="Base directory for Antigravity IDE data")
    conversations_dir: Path = Field(description="Directory containing conversation SQLite databases")
    brain_dir: Path = Field(description="Directory containing session brain logs and artifacts")

    @classmethod
    def discover(
        cls,
        base_dir: Optional[str | Path] = None,
        conversations_dir: Optional[str | Path] = None,
        brain_dir: Optional[str | Path] = None,
    ) -> AntigravityConfig:
        """Discover and resolve Antigravity storage paths with sensible fallbacks."""
        # 1. Resolve base directory
        if base_dir:
            resolved_base = Path(base_dir).expanduser().resolve()
        elif "ANTIGRAVITY_BASE_DIR" in os.environ:
            resolved_base = Path(os.environ["ANTIGRAVITY_BASE_DIR"]).expanduser().resolve()
        else:
            candidates = [
                Path.home() / ".gemini" / "antigravity-ide",
                Path.home() / ".gemini" / "antigravity",
            ]
            resolved_base = candidates[0]
            for candidate in candidates:
                if candidate.exists():
                    resolved_base = candidate
                    break

        # 2. Resolve conversations directory
        if conversations_dir:
            resolved_conv = Path(conversations_dir).expanduser().resolve()
        elif "ANTIGRAVITY_CONVERSATIONS_DIR" in os.environ:
            resolved_conv = Path(os.environ["ANTIGRAVITY_CONVERSATIONS_DIR"]).expanduser().resolve()
        else:
            resolved_conv = resolved_base / "conversations"

        # 3. Resolve brain directory
        if brain_dir:
            resolved_brain = Path(brain_dir).expanduser().resolve()
        elif "ANTIGRAVITY_BRAIN_DIR" in os.environ:
            resolved_brain = Path(os.environ["ANTIGRAVITY_BRAIN_DIR"]).expanduser().resolve()
        else:
            resolved_brain = resolved_base / "brain"

        return cls(
            base_dir=resolved_base,
            conversations_dir=resolved_conv,
            brain_dir=resolved_brain,
        )

    def get_conversation_db(self, conversation_id: str) -> Path:
        """Return the SQLite database path for a given conversation ID."""
        return self.conversations_dir / f"{conversation_id}.db"

    def get_brain_dir(self, conversation_id: str) -> Path:
        """Return the brain folder path for a given conversation ID."""
        return self.brain_dir / conversation_id

    def get_transcript_path(self, conversation_id: str) -> Optional[Path]:
        """Return the transcript_full.jsonl or transcript.jsonl path."""
        logs_dir = self.get_brain_dir(conversation_id) / ".system_generated" / "logs"
        full = logs_dir / "transcript_full.jsonl"
        if full.exists():
            return full
        compact = logs_dir / "transcript.jsonl"
        if compact.exists():
            return compact
        return None

    def get_plan_path(self, conversation_id: str) -> Optional[Path]:
        """Return implementation_plan.md path if it exists."""
        plan = self.get_brain_dir(conversation_id) / "implementation_plan.md"
        return plan if plan.exists() else None

    def get_walkthrough_path(self, conversation_id: str) -> Optional[Path]:
        """Return walkthrough.md path if it exists."""
        wt = self.get_brain_dir(conversation_id) / "walkthrough.md"
        return wt if wt.exists() else None
