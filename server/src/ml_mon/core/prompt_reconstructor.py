"""Reconstructs the full raw prompt and structured components from Antigravity generation snapshots."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from ml_mon.config import AntigravityConfig


class ToolParameterProperty(BaseModel):
    """Parameter property schema definition."""
    name: str
    type_name: str = "string"
    description: str = ""
    required: bool = False


class ReconstructedTool(BaseModel):
    """Extracted tool declaration from the generation prompt."""
    name: str
    description: str
    parameters_schema: Optional[dict[str, Any]] = None
    char_count: int = 0
    est_tokens: int = 0


class PromptSection(BaseModel):
    """A semantic section of the reconstructed model prompt."""
    id: str
    title: str
    category: str  # system_instruction, skills_plugins, tools, environment_memory, conversation_history
    char_count: int
    est_tokens: int
    content: str


class ReconstructedPrompt(BaseModel):
    """Complete reconstructed prompt and its semantic parts."""
    conversation_id: str
    model_name: Optional[str] = None
    snapshot_step: int = 0
    total_chars: int = 0
    total_est_tokens: int = 0
    sections: list[PromptSection] = Field(default_factory=list)
    tools: list[ReconstructedTool] = Field(default_factory=list)
    raw_prompt_text: str = ""


class ProtobufReader:
    """Lightweight pure-Python protobuf stream parser."""

    @staticmethod
    def parse_varint(data: bytes, pos: int) -> tuple[int, int]:
        val = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return val, pos

    @classmethod
    def extract_strings(cls, data: bytes, pos: int = 0, max_depth: int = 4) -> list[tuple[int, str]]:
        """Extract all valid UTF-8 string nodes from protobuf bytes."""
        strings: list[tuple[int, str]] = []
        end = len(data)
        while pos < end:
            try:
                tag, next_pos = cls.parse_varint(data, pos)
                if next_pos == pos:
                    break
                pos = next_pos
                field_num = tag >> 3
                wire_type = tag & 0x07

                if wire_type == 0:
                    _, pos = cls.parse_varint(data, pos)
                elif wire_type == 1:
                    pos += 8
                elif wire_type == 2:
                    length, pos = cls.parse_varint(data, pos)
                    if pos + length > end:
                        break
                    chunk = data[pos : pos + length]
                    pos += length
                    try:
                        s = chunk.decode("utf-8")
                        if len(s) > 15:
                            strings.append((field_num, s))
                    except UnicodeDecodeError:
                        if max_depth > 0 and len(chunk) > 10:
                            strings.extend(cls.extract_strings(chunk, 0, max_depth - 1))
                elif wire_type == 5:
                    pos += 4
                else:
                    break
            except Exception:
                break
        return strings


class PromptReconstructor:
    """Extracts, parses, and reconstructs the full prompt from Antigravity storage."""

    def __init__(self, config: Optional[AntigravityConfig] = None):
        self.config = config or AntigravityConfig.discover()

    def reconstruct(self, conversation_id: str) -> Optional[ReconstructedPrompt]:
        """Reconstruct the prompt from SQLite generation metadata or fallback to transcript."""
        db_path = self.config.get_conversation_db(conversation_id)

        # 1. Attempt extraction from SQLite gen_metadata snapshot
        if db_path.exists():
            prompt = self._reconstruct_from_sqlite(conversation_id, db_path)
            if prompt:
                return prompt

        # 2. Fallback: reconstruct from transcript
        return self._reconstruct_from_transcript(conversation_id)

    def _reconstruct_from_sqlite(self, conversation_id: str, db_path: Path) -> Optional[ReconstructedPrompt]:
        """Parse raw protobuf generation snapshot from SQLite gen_metadata."""
        try:
            uri = f"file:{db_path}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT idx, size, data FROM gen_metadata WHERE size > 50000 ORDER BY idx DESC LIMIT 1"
                )
                row = cur.fetchone()
                if not row:
                    return None
                step_idx, size, raw_blob = row
        except Exception:
            return None

        # Extract system instruction starting at <identity>
        pos_id = raw_blob.find(b"<identity>")
        if pos_id == -1:
            pos_id = raw_blob.find(b"You are Antigravity")

        extracted_strings = ProtobufReader.extract_strings(raw_blob)

        # 1. Parse Tool Declarations
        tools: list[ReconstructedTool] = []
        seen_tools = set()

        # Tools are defined as JSON schemas or descriptions in field 2 or 3
        for i, (fn, s) in enumerate(extracted_strings):
            if '"$schema"' in s or '"properties"' in s and '"required"' in s:
                try:
                    schema = json.loads(s)
                    desc = ""
                    if i > 0 and len(extracted_strings[i - 1][1]) < 5000:
                        desc = extracted_strings[i - 1][1]
                    props = schema.get("properties", {})
                    tool_name = "custom_tool"
                    if "CommandLine" in props:
                        tool_name = "run_command"
                    elif "ReplacementChunks" in props:
                        tool_name = "multi_replace_file_content"
                    elif "ReplacementContent" in props:
                        tool_name = "replace_file_content"
                    elif "DirectoryPath" in props:
                        tool_name = "list_dir"
                    elif "SearchPath" in props:
                        tool_name = "grep_search"
                    elif "AbsolutePath" in props:
                        tool_name = "view_file"
                    elif "Overwrite" in props and "CodeContent" in props:
                        tool_name = "write_to_file"
                    elif "RecordingName" in props:
                        tool_name = "browser_subagent"
                    elif "Prompt" in props and "ImageName" in props:
                        tool_name = "generate_image"
                    elif "CronExpression" in props or "DurationSeconds" in props:
                        tool_name = "schedule"
                    elif "TaskId" in props:
                        tool_name = "manage_task"
                    elif "questions" in props:
                        tool_name = "ask_question"
                    elif "query" in props:
                        tool_name = "search_web"
                    elif "Url" in props:
                        tool_name = "read_url_content"

                    if tool_name not in seen_tools:
                        seen_tools.add(tool_name)
                        char_count = len(s) + len(desc)
                        tools.append(
                            ReconstructedTool(
                                name=tool_name,
                                description=desc or schema.get("description", ""),
                                parameters_schema=schema,
                                char_count=char_count,
                                est_tokens=(char_count + 3) // 4,
                            )
                        )
                except Exception:
                    pass

        # 2. Build Structured Sections
        sections: list[PromptSection] = []

        system_text = ""
        pos_compaction = raw_blob.find(b"# Resuming from a compaction")
        if pos_compaction == -1:
            pos_compaction = raw_blob.find(b"<USER_REQUEST>")

        if pos_id != -1 and pos_compaction != -1 and pos_compaction > pos_id:
            raw_sys = raw_blob[pos_id:pos_compaction]
            system_text = raw_sys.decode("utf-8", errors="replace")
        elif pos_id != -1:
            raw_sys = raw_blob[pos_id : pos_id + 75000]
            system_text = raw_sys.decode("utf-8", errors="replace")

        # Split system_text into components: Base Persona vs Skills/Plugins
        if system_text:
            pos_skills = system_text.find("<skills>")
            pos_plugins = system_text.find("<plugins>")
            split_pos = pos_skills if pos_skills != -1 else pos_plugins

            if split_pos != -1:
                base_persona = system_text[:split_pos].strip()
                skills_plugins = system_text[split_pos:].strip()
            else:
                base_persona = system_text.strip()
                skills_plugins = ""

            if base_persona:
                c_len = len(base_persona)
                sections.append(
                    PromptSection(
                        id="sec-base-persona",
                        title="🧠 Base System Identity & Core Guidelines",
                        category="system_instruction",
                        char_count=c_len,
                        est_tokens=(c_len + 3) // 4,
                        content=base_persona,
                    )
                )

            if skills_plugins:
                c_len = len(skills_plugins)
                sections.append(
                    PromptSection(
                        id="sec-skills-plugins",
                        title="🧩 Skills, Customizations & Plugins Catalog",
                        category="skills_plugins",
                        char_count=c_len,
                        est_tokens=(c_len + 3) // 4,
                        content=skills_plugins,
                    )
                )

        # 3. Tool Function Declarations Section
        if tools:
            tool_content = "\n\n".join(
                f"### declaration: {t.name}\n{t.description}\n```json\n{json.dumps(t.parameters_schema, indent=2)}\n```"
                for t in tools
            )
            t_len = len(tool_content)
            sections.append(
                PromptSection(
                    id="sec-tool-declarations",
                    title=f"🛠️ Tool Declarations & JSON Schemas ({len(tools)} tools)",
                    category="tools",
                    char_count=t_len,
                    est_tokens=(t_len + 3) // 4,
                    content=tool_content,
                )
            )

        # 4. Compaction & Memory State
        if pos_compaction != -1:
            pos_history = raw_blob.find(b"<USER_REQUEST>", pos_compaction)
            if pos_history != -1:
                compaction_chunk = raw_blob[pos_compaction:pos_history].decode("utf-8", errors="replace").strip()
                if compaction_chunk:
                    cp_len = len(compaction_chunk)
                    sections.append(
                        PromptSection(
                            id="sec-compaction-memory",
                            title="⚙️ Compaction Summary & Resumption State",
                            category="environment_memory",
                            char_count=cp_len,
                            est_tokens=(cp_len + 3) // 4,
                            content=compaction_chunk,
                        )
                    )

        # 5. Dynamic Conversation & Tool Output Trajectory
        history_text = self._extract_active_history_text(conversation_id)
        if history_text:
            h_len = len(history_text)
            sections.append(
                PromptSection(
                    id="sec-dynamic-history",
                    title="💬 Active Trajectory & Tool Execution History",
                    category="conversation_history",
                    char_count=h_len,
                    est_tokens=(h_len + 3) // 4,
                    content=history_text,
                )
            )

        # Assemble full raw text
        raw_parts = [s.content for s in sections]
        full_raw = "\n\n" + ("=" * 60) + "\n\n".join(raw_parts)

        total_chars = sum(s.char_count for s in sections)
        total_tokens = sum(s.est_tokens for s in sections)

        # Model name
        from ml_mon.core.scanner import ConversationScanner
        scanner = ConversationScanner(self.config)
        model_name = scanner._extract_model_name(self.config.get_transcript_path(conversation_id), db_path)

        return ReconstructedPrompt(
            conversation_id=conversation_id,
            model_name=model_name or "Gemini",
            snapshot_step=step_idx,
            total_chars=total_chars,
            total_est_tokens=total_tokens,
            sections=sections,
            tools=tools,
            raw_prompt_text=full_raw,
        )

    def _extract_active_history_text(self, conversation_id: str) -> str:
        """Extract formatted active conversation history from transcript."""
        transcript_path = self.config.get_transcript_path(conversation_id)
        if not transcript_path or not transcript_path.exists():
            return ""

        lines: list[str] = []
        last_checkpoint_step: Optional[int] = None
        records: list[dict[str, Any]] = []

        try:
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        records.append(rec)
                        if rec.get("type") == "CHECKPOINT":
                            last_checkpoint_step = rec.get("step_index", 0)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return ""

        for r in records:
            step_idx = r.get("step_index", 0)
            if last_checkpoint_step is not None and step_idx < last_checkpoint_step:
                continue

            stype = r.get("type", "STEP")
            content = r.get("content") or ""

            if stype == "USER_INPUT":
                lines.append(f"### [USER_INPUT (Step {step_idx})]\n{content}")
            elif stype == "PLANNER_RESPONSE":
                thinking = r.get("thinking")
                tool_calls = r.get("tool_calls")
                if thinking:
                    lines.append(f"### [MODEL THINKING / CoT (Step {step_idx})]\n{thinking.strip()}")
                if tool_calls:
                    lines.append(f"### [TOOL INVOCATION (Step {step_idx})]\n```json\n{json.dumps(tool_calls, indent=2)}\n```")
                if content and not tool_calls:
                    lines.append(f"### [ASSISTANT RESPONSE (Step {step_idx})]\n{content}")
            elif stype != "CHECKPOINT":
                lines.append(f"### [TOOL RESULT: {stype} (Step {step_idx})]\n{content}")

        return "\n\n".join(lines)

    def _reconstruct_from_transcript(self, conversation_id: str) -> Optional[ReconstructedPrompt]:
        """Fallback to transcript when SQLite gen_metadata snapshot is absent."""
        history_text = self._extract_active_history_text(conversation_id)
        if not history_text:
            return None

        h_len = len(history_text)
        section = PromptSection(
            id="sec-dynamic-history",
            title="💬 Active Trajectory & Tool Execution History",
            category="conversation_history",
            char_count=h_len,
            est_tokens=(h_len + 3) // 4,
            content=history_text,
        )

        return ReconstructedPrompt(
            conversation_id=conversation_id,
            model_name="Gemini",
            snapshot_step=0,
            total_chars=h_len,
            total_est_tokens=(h_len + 3) // 4,
            sections=[section],
            tools=[],
            raw_prompt_text=history_text,
        )
