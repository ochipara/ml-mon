"""Parser for Antigravity JSONL transcripts, CoT thoughts, tool calls, plans, and rich analytics."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ml_mon.config import AntigravityConfig
from ml_mon.core.models import (
    ContextEvolutionReport,
    ContextFrame,
    ContextWindowReport,
    ConversationDetail,
    ConversationSummary,
    EvolutionBreakdown,
    EvolutionStepPoint,
    FileModification,
    MediaArtifact,
    PlanAsset,
    SessionAnalytics,
    StepRecord,
    Thought,
    ToolCall,
    ToolResult,
    UsageBreakdown,
    UserEnvironment,
)
from ml_mon.core.scanner import ConversationScanner


class ConversationParser:
    """Parses transcript logs and associated planning artifacts into structured models."""

    def __init__(self, config: Optional[AntigravityConfig] = None):
        self.config = config or AntigravityConfig.discover()
        self.scanner = ConversationScanner(self.config)

    def parse_conversation(self, conversation_id: str) -> Optional[ConversationDetail]:
        """Parse complete conversation history, thoughts, plan documents, and rich analytics."""
        summary = self.scanner.get_summary(conversation_id)
        if not summary:
            return None

        transcript_path = self.config.get_transcript_path(conversation_id)
        steps: list[StepRecord] = []
        thoughts: list[Thought] = []
        tool_counts: dict[str, int] = {}
        error_count = 0
        checkpoint_count = 0
        touched_files_map: dict[str, FileModification] = {}
        latest_environment: Optional[UserEnvironment] = None
        extracted_model_name: Optional[str] = None

        prev_timestamp: Optional[datetime] = None

        if transcript_path and transcript_path.exists():
            with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        record = json.loads(line_str)
                    except json.JSONDecodeError:
                        continue

                    # Calculate duration if timestamps present
                    curr_timestamp = None
                    duration: Optional[float] = None
                    if "created_at" in record:
                        try:
                            # Parse ISO timestamp like "2026-09-23T18:41:41Z"
                            ts_str = record["created_at"].rstrip("Z")
                            curr_timestamp = datetime.fromisoformat(ts_str)
                            if prev_timestamp:
                                delta = (curr_timestamp - prev_timestamp).total_seconds()
                                if 0.0 <= delta < 3600.0:  # reasonable step boundary
                                    duration = round(delta, 2)
                        except Exception:
                            pass

                    step = self.parse_step_record(record, duration=duration)
                    if curr_timestamp:
                        prev_timestamp = curr_timestamp

                    steps.append(step)
                    if step.thought:
                        step.thought.duration_seconds = duration
                        thoughts.append(step.thought)

                    # Extract model from settings change or prompt
                    raw_text = record.get("content", "")
                    if "USER_SETTINGS_CHANGE" in raw_text:
                        m = re.search(r"Model Selection` from .*? to (.*?)(?:\.\s*No need|\.\s*\n|\.\s*$|\.$)", raw_text)
                        if m:
                            extracted_model_name = m.group(1).strip()

                    # Extract IDE environment from user input
                    if step.step_type == "USER_INPUT" and record.get("content"):
                        env = self._extract_user_environment(record["content"])
                        if env:
                            if extracted_model_name and not env.model_name:
                                env.model_name = extracted_model_name
                            latest_environment = env

                    # Track tool frequencies
                    for tc in step.tool_calls:
                        tool_counts[tc.name] = tool_counts.get(tc.name, 0) + 1

                        # Track modified/created files
                        if tc.name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                            target_file = tc.args.get("TargetFile")
                            if target_file and isinstance(target_file, str):
                                clean_path = target_file.strip('"\'')
                                op = "create" if tc.name == "write_to_file" else "modify"
                                touched_files_map[clean_path] = FileModification(
                                    path=clean_path,
                                    operation=op,
                                    step_index=step.step_index,
                                    tool_name=tc.name,
                                )

                    # Track errors
                    if step.is_error:
                        error_count += 1

                    # Track checkpoints
                    if step.is_checkpoint:
                        checkpoint_count += 1

        plan = self.parse_plan_asset(conversation_id)

        # Collect media artifacts (screenshots, recordings, tasks)
        media_artifacts = self._collect_media_artifacts(conversation_id)

        # Update summary model name
        if latest_environment and latest_environment.model_name:
            summary.model_name = latest_environment.model_name
        elif extracted_model_name:
            summary.model_name = extracted_model_name

        analytics = SessionAnalytics(
            model_name=summary.model_name,
            total_thoughts=len(thoughts),
            total_thinking_chars=sum(t.character_count for t in thoughts),
            tool_counts=tool_counts,
            error_count=error_count,
            checkpoint_count=checkpoint_count,
            touched_files=list(touched_files_map.values()),
            environment=latest_environment,
            media_artifacts=media_artifacts,
        )

        return ConversationDetail(
            summary=summary,
            steps=steps,
            thoughts=thoughts,
            plan=plan,
            analytics=analytics,
        )

    def parse_step_record(self, record: dict[str, Any], duration: Optional[float] = None) -> StepRecord:
        """Parse a single raw JSON record into a typed StepRecord."""
        step_index = record.get("step_index", 0)
        source = record.get("source", "UNKNOWN")
        step_type = record.get("type", "UNKNOWN")
        status = record.get("status", "DONE")
        created_at = record.get("created_at")
        content = record.get("content")

        thought: Optional[Thought] = None
        thinking_text = record.get("thinking")
        if thinking_text and thinking_text.strip():
            thought = Thought(
                step_index=step_index,
                created_at=created_at,
                duration_seconds=duration,
                content=thinking_text.strip(),
            )

        # Parse tool calls
        tool_calls: list[ToolCall] = []
        for tc in record.get("tool_calls", []):
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            action = args.get("toolAction")
            summary = args.get("toolSummary")
            tool_calls.append(
                ToolCall(
                    call_id=tc.get("id"),
                    name=name,
                    args=args,
                    action=str(action).strip('"') if action else None,
                    summary=str(summary).strip('"') if summary else None,
                )
            )

        # Parse user prompt
        user_prompt: Optional[str] = None
        if step_type == "USER_INPUT" and content:
            user_prompt = self._extract_user_request(content)

        # Parse tool execution result
        tool_result: Optional[ToolResult] = None
        is_error = False
        if step_type in (
            "RUN_COMMAND",
            "VIEW_FILE",
            "WRITE_TO_FILE",
            "REPLACE_FILE_CONTENT",
            "MULTI_REPLACE_FILE_CONTENT",
            "LIST_DIR",
            "GREP_SEARCH",
            "SEARCH_WEB",
            "READ_URL_CONTENT",
            "BROWSER_SUBAGENT",
            "ASK_QUESTION",
        ):
            exit_code = record.get("exit_code")
            if exit_code is not None and exit_code != 0:
                is_error = True
            if status in ("ERROR", "FAILED"):
                is_error = True

            tool_result = ToolResult(
                step_index=step_index,
                tool_name=step_type,
                status=status,
                exit_code=exit_code,
                content=content,
                truncated=bool(record.get("truncated_fields")),
                duration_seconds=duration,
            )

        is_checkpoint = step_type == "CHECKPOINT"

        # Model text response (excluding tool call declarations)
        model_response: Optional[str] = None
        if source == "MODEL" and content and not tool_calls and step_type == "PLANNER_RESPONSE":
            model_response = content

        return StepRecord(
            step_index=step_index,
            source=source,
            step_type=step_type,
            status=status,
            created_at=created_at,
            duration_seconds=duration,
            is_checkpoint=is_checkpoint,
            is_error=is_error,
            thought=thought,
            tool_calls=tool_calls,
            tool_result=tool_result,
            user_prompt=user_prompt,
            model_response=model_response,
            raw_content=content if step_type not in ("USER_INPUT",) else None,
        )

    def parse_plan_asset(self, conversation_id: str) -> Optional[PlanAsset]:
        """Load implementation_plan.md and walkthrough.md if present."""
        plan_path = self.config.get_plan_path(conversation_id)
        walkthrough_path = self.config.get_walkthrough_path(conversation_id)

        if not plan_path and not walkthrough_path:
            return None

        plan_content: Optional[str] = None
        plan_mtime: Optional[str] = None
        if plan_path and plan_path.exists():
            try:
                plan_content = plan_path.read_text(encoding="utf-8", errors="ignore")
                plan_mtime = datetime.fromtimestamp(plan_path.stat().st_mtime).isoformat()
            except Exception:
                pass

        wt_content: Optional[str] = None
        wt_mtime: Optional[str] = None
        if walkthrough_path and walkthrough_path.exists():
            try:
                wt_content = walkthrough_path.read_text(encoding="utf-8", errors="ignore")
                wt_mtime = datetime.fromtimestamp(walkthrough_path.stat().st_mtime).isoformat()
            except Exception:
                pass

        return PlanAsset(
            plan_path=str(plan_path) if plan_path else None,
            plan_content=plan_content,
            plan_last_modified=plan_mtime,
            walkthrough_path=str(walkthrough_path) if walkthrough_path else None,
            walkthrough_content=wt_content,
            walkthrough_last_modified=wt_mtime,
        )

    def _extract_user_request(self, content: str) -> str:
        """Strip IDE tags to isolate user's actual prompt."""
        match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.strip()

    def _extract_user_environment(self, content: str) -> Optional[UserEnvironment]:
        """Extract active document, open documents, running commands, and model from prompt."""
        meta_match = re.search(r"<ADDITIONAL_METADATA>(.*?)</ADDITIONAL_METADATA>", content, re.DOTALL)
        if not meta_match:
            return None

        text = meta_match.group(1)
        active_doc = None
        cursor_line = None
        open_docs: list[str] = []
        commands: list[str] = []

        # Active Document: /path/to/file (LANG)
        ad_match = re.search(r"Active Document:\s*(.*?)(?:\s*\([A-Z_]+\))?$", text, re.MULTILINE)
        if ad_match:
            active_doc = ad_match.group(1).strip()

        # Cursor is on line: 12
        cur_match = re.search(r"Cursor is on line:\s*(\d+)", text)
        if cur_match:
            cursor_line = int(cur_match.group(1))

        # Other open documents:
        if "Other open documents:" in text:
            docs_block = text.split("Other open documents:")[1].split("Running terminal commands:")[0]
            for l in docs_block.splitlines():
                l = l.strip("- \t\r")
                if l and not l.startswith("Cursor"):
                    doc_path = l.split(" (")[0].strip()
                    if doc_path:
                        open_docs.append(doc_path)

        # Running terminal commands:
        if "Running terminal commands:" in text:
            cmds_block = text.split("Running terminal commands:")[1].split("Browser State:")[0]
            for l in cmds_block.splitlines():
                l = l.strip("- \t\r")
                if l:
                    commands.append(l)

        return UserEnvironment(
            active_document=active_doc,
            cursor_line=cursor_line,
            open_documents=open_docs,
            running_commands=commands,
        )

    def _collect_media_artifacts(self, conversation_id: str) -> list[MediaArtifact]:
        """Collect all screenshots, video recordings, and task logs in brain directory."""
        brain_dir = self.config.get_brain_dir(conversation_id)
        if not brain_dir.exists():
            return []

        artifacts: list[MediaArtifact] = []

        # 1. Images and recordings directly in brain folder
        for ext, media_type in (
            ("*.png", "image"),
            ("*.jpg", "image"),
            ("*.jpeg", "image"),
            ("*.webp", "video"),
            ("*.mp4", "video"),
        ):
            for p in brain_dir.glob(ext):
                if p.is_file():
                    st = p.stat()
                    artifacts.append(
                        MediaArtifact(
                            name=p.name,
                            path=str(p),
                            relative_url=f"/api/artifacts/{conversation_id}/{p.name}",
                            media_type=media_type,
                            size_bytes=st.st_size,
                            modified_at=datetime.fromtimestamp(st.st_mtime).isoformat(),
                        )
                    )

        # 2. Task logs in .system_generated/tasks/
        tasks_dir = brain_dir / ".system_generated" / "tasks"
        if tasks_dir.exists():
            for p in tasks_dir.glob("*.log"):
                if p.is_file():
                    st = p.stat()
                    artifacts.append(
                        MediaArtifact(
                            name=f"Task Log: {p.stem}",
                            path=str(p),
                            relative_url=f"/api/artifacts/{conversation_id}/tasks/{p.name}",
                            media_type="log",
                            size_bytes=st.st_size,
                            modified_at=datetime.fromtimestamp(st.st_mtime).isoformat(),
                        )
                    )

        return artifacts

    def extract_context_window(self, conversation_id: str) -> Optional[ContextWindowReport]:
        """Extract all message frames, determine active compaction boundaries, and compute usage statistics."""
        transcript_path = self.config.get_transcript_path(conversation_id)
        if not transcript_path.exists():
            return None

        records: list[dict[str, Any]] = []
        last_checkpoint_step: Optional[int] = None
        compaction_count = 0

        try:
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        records.append(record)
                        if record.get("type") == "CHECKPOINT":
                            compaction_count += 1
                            last_checkpoint_step = record.get("step_index", 0)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return None

        active_window_start = last_checkpoint_step if last_checkpoint_step is not None else 0
        has_compaction = last_checkpoint_step is not None

        frames: list[ContextFrame] = []
        frame_idx = 0

        for r in records:
            step_index = r.get("step_index", 0)
            source = r.get("source", "UNKNOWN")
            step_type = r.get("type", "UNKNOWN")
            content = r.get("content") or ""
            is_active = (last_checkpoint_step is None) or (step_index >= last_checkpoint_step)

            if step_type == "CHECKPOINT":
                char_count = len(content)
                preview = content[:200] + ("..." if len(content) > 200 else "")
                frames.append(
                    ContextFrame(
                        index=frame_idx,
                        step_index=step_index,
                        source=source,
                        frame_type="CHECKPOINT",
                        category="compaction_summary",
                        title=f"⚙️ Checkpoint Compaction (Step {step_index})",
                        char_count=char_count,
                        est_tokens=(char_count + 3) // 4,
                        is_active=is_active,
                        preview=preview,
                        full_content=content,
                    )
                )
                frame_idx += 1

            elif step_type == "USER_INPUT":
                char_count = len(content)
                preview = content[:200] + ("..." if len(content) > 200 else "")
                frames.append(
                    ContextFrame(
                        index=frame_idx,
                        step_index=step_index,
                        source=source,
                        frame_type="USER_INPUT",
                        category="user_prompts",
                        title=f"👤 User Request & IDE Context (Step {step_index})",
                        char_count=char_count,
                        est_tokens=(char_count + 3) // 4,
                        is_active=is_active,
                        preview=preview,
                        full_content=content,
                    )
                )
                frame_idx += 1

            elif step_type == "CONVERSATION_HISTORY":
                char_count = len(content)
                preview = content[:200] + ("..." if len(content) > 200 else "")
                frames.append(
                    ContextFrame(
                        index=frame_idx,
                        step_index=step_index,
                        source=source,
                        frame_type="CONVERSATION_HISTORY",
                        category="system_history",
                        title=f"📜 Past Conversation History (Step {step_index})",
                        char_count=char_count,
                        est_tokens=(char_count + 3) // 4,
                        is_active=is_active,
                        preview=preview,
                        full_content=content,
                    )
                )
                frame_idx += 1

            elif step_type == "KNOWLEDGE_ARTIFACTS":
                char_count = len(content)
                preview = content[:200] + ("..." if len(content) > 200 else "")
                frames.append(
                    ContextFrame(
                        index=frame_idx,
                        step_index=step_index,
                        source=source,
                        frame_type="KNOWLEDGE_ARTIFACTS",
                        category="system_history",
                        title=f"📚 Knowledge Base Items (Step {step_index})",
                        char_count=char_count,
                        est_tokens=(char_count + 3) // 4,
                        is_active=is_active,
                        preview=preview,
                        full_content=content,
                    )
                )
                frame_idx += 1

            elif step_type == "SYSTEM_MESSAGE":
                char_count = len(content)
                preview = content[:200] + ("..." if len(content) > 200 else "")
                frames.append(
                    ContextFrame(
                        index=frame_idx,
                        step_index=step_index,
                        source=source,
                        frame_type="SYSTEM_MESSAGE",
                        category="system_history",
                        title=f"ℹ️ System Directive (Step {step_index})",
                        char_count=char_count,
                        est_tokens=(char_count + 3) // 4,
                        is_active=is_active,
                        preview=preview,
                        full_content=content,
                    )
                )
                frame_idx += 1

            elif step_type == "PLANNER_RESPONSE":
                # Check for thinking
                thinking = r.get("thinking")
                if thinking and thinking.strip():
                    th_text = thinking.strip()
                    char_count = len(th_text)
                    preview = th_text[:200] + ("..." if len(th_text) > 200 else "")
                    frames.append(
                        ContextFrame(
                            index=frame_idx,
                            step_index=step_index,
                            source=source,
                            frame_type="COT",
                            category="cot_reasoning",
                            title=f"🧠 Chain of Thought (Step {step_index})",
                            char_count=char_count,
                            est_tokens=(char_count + 3) // 4,
                            is_active=is_active,
                            preview=preview,
                            full_content=th_text,
                        )
                    )
                    frame_idx += 1

                # Check for tool calls
                tool_calls = r.get("tool_calls", [])
                if tool_calls:
                    tc_text = json.dumps(tool_calls, indent=2)
                    char_count = len(tc_text)
                    tool_names = ", ".join(t.get("name", "tool") for t in tool_calls)
                    preview = f"{len(tool_calls)} call(s): {tool_names}"
                    frames.append(
                        ContextFrame(
                            index=frame_idx,
                            step_index=step_index,
                            source=source,
                            frame_type="TOOL_CALL",
                            category="tool_outputs",
                            title=f"🛠️ Tool Invocation: {tool_names} (Step {step_index})",
                            char_count=char_count,
                            est_tokens=(char_count + 3) // 4,
                            is_active=is_active,
                            preview=preview,
                            full_content=tc_text,
                        )
                    )
                    frame_idx += 1

                # Check for assistant response text
                if content and not tool_calls:
                    char_count = len(content)
                    preview = content[:200] + ("..." if len(content) > 200 else "")
                    frames.append(
                        ContextFrame(
                            index=frame_idx,
                            step_index=step_index,
                            source=source,
                            frame_type="ASSISTANT",
                            category="assistant_responses",
                            title=f"🤖 Assistant Response (Step {step_index})",
                            char_count=char_count,
                            est_tokens=(char_count + 3) // 4,
                            is_active=is_active,
                            preview=preview,
                            full_content=content,
                        )
                    )
                    frame_idx += 1

            else:
                # Tool outputs and other steps
                char_count = len(content)
                preview = content[:200] + ("..." if len(content) > 200 else "")
                frames.append(
                    ContextFrame(
                        index=frame_idx,
                        step_index=step_index,
                        source=source,
                        frame_type=step_type,
                        category="tool_outputs",
                        title=f"📥 Tool Result: {step_type} (Step {step_index})",
                        char_count=char_count,
                        est_tokens=(char_count + 3) // 4,
                        is_active=is_active,
                        preview=preview,
                        full_content=content,
                    )
                )
                frame_idx += 1

        # Check if we have raw prompt snapshots from SQLite gen_metadata
        has_prompt_snapshot = False
        sys_tokens = 0
        sys_chars = 0
        tool_tokens = 0
        tool_chars = 0

        try:
            from ml_mon.core.prompt_reconstructor import PromptReconstructor
            reconstructor = PromptReconstructor(self.config)
            prompt_rec = reconstructor.reconstruct(conversation_id)
            if prompt_rec and prompt_rec.tools:
                has_prompt_snapshot = True
                for sec in prompt_rec.sections:
                    if sec.category in ("system_instruction", "skills_plugins"):
                        sys_tokens += sec.est_tokens
                        sys_chars += sec.char_count
                    elif sec.category == "tools":
                        tool_tokens += sec.est_tokens
                        tool_chars += sec.char_count
        except Exception:
            pass

        # Insert baseline frames at the beginning if present
        all_frames: list[ContextFrame] = []
        if has_prompt_snapshot and sys_tokens > 0:
            all_frames.append(
                ContextFrame(
                    index=0,
                    step_index=0,
                    source="SYSTEM",
                    frame_type="SYSTEM_PROMPT",
                    category="system_instruction",
                    title="🧠 System Persona & Skill Instructions",
                    char_count=sys_chars,
                    est_tokens=sys_tokens,
                    is_active=True,
                    preview="Base Antigravity agent identity, guidelines, and skills/plugins catalog.",
                    full_content="[Extracted from generation snapshot in SQLite gen_metadata]",
                )
            )

        if has_prompt_snapshot and tool_tokens > 0:
            all_frames.append(
                ContextFrame(
                    index=len(all_frames),
                    step_index=0,
                    source="SYSTEM",
                    frame_type="TOOL_DECLARATIONS",
                    category="tool_declarations",
                    title="🛠️ Tool Function Declarations & JSON Schemas",
                    char_count=tool_chars,
                    est_tokens=tool_tokens,
                    is_active=True,
                    preview="Function declarations and parameters schemas for available IDE tools.",
                    full_content="[Extracted from generation snapshot in SQLite gen_metadata]",
                )
            )

        # Shift existing frame indices
        offset = len(all_frames)
        for f in frames:
            f.index += offset
            all_frames.append(f)

        active_frames = [f for f in all_frames if f.is_active]
        total_active_chars = sum(f.char_count for f in active_frames)
        total_active_tokens = sum(f.est_tokens for f in active_frames)
        total_session_chars = sum(f.char_count for f in all_frames)
        total_session_tokens = sum(f.est_tokens for f in all_frames)

        # Build usage breakdown for active context
        categories_def = [
            ("system_instruction", "System Persona & Skills"),
            ("tool_declarations", "Tool Declarations & Schemas"),
            ("compaction_summary", "Checkpoint & Compaction"),
            ("user_prompts", "User Requests & IDE Context"),
            ("cot_reasoning", "Chain of Thought (CoT)"),
            ("tool_outputs", "Tool Calls & Results"),
            ("assistant_responses", "Assistant Responses"),
            ("system_history", "System History & Memory"),
        ]

        breakdowns: list[UsageBreakdown] = []
        for cat_key, cat_label in categories_def:
            cat_chars = sum(f.char_count for f in active_frames if f.category == cat_key)
            cat_tokens = sum(f.est_tokens for f in active_frames if f.category == cat_key)
            pct = round((cat_tokens / total_active_tokens) * 100, 1) if total_active_tokens > 0 else 0.0
            breakdowns.append(
                UsageBreakdown(
                    category=cat_key,
                    label=cat_label,
                    char_count=cat_chars,
                    est_tokens=cat_tokens,
                    percentage=pct,
                )
            )

        # 5. Extract Step-by-Step Context & Prompt Evolution
        evolution = self.extract_context_evolution(
            conversation_id=conversation_id,
            frames=frames,
            system_tokens=sys_tokens,
            tool_tokens=tool_tokens,
        )

        return ContextWindowReport(
            conversation_id=conversation_id,
            active_window_start_step=active_window_start,
            has_compaction=has_compaction,
            compaction_count=compaction_count,
            total_active_chars=total_active_chars,
            total_active_tokens=total_active_tokens,
            total_session_chars=total_session_chars,
            total_session_tokens=total_session_tokens,
            has_prompt_snapshot=has_prompt_snapshot,
            system_prompt_tokens=sys_tokens,
            tool_declarations_tokens=tool_tokens,
            breakdown=breakdowns,
            frames=all_frames,
            evolution=evolution,
        )

    def extract_context_evolution(
        self,
        conversation_id: str,
        frames: list[ContextFrame],
        system_tokens: int,
        tool_tokens: int,
    ) -> ContextEvolutionReport:
        """Compute the step-by-step token state and component breakdown across the entire session."""
        if not frames:
            return ContextEvolutionReport(conversation_id=conversation_id)

        from collections import defaultdict

        checkpoints = sorted(list(set(f.step_index for f in frames if f.frame_type == "CHECKPOINT")))
        checkpoints_set = set(checkpoints)

        frames_by_step: dict[int, list[ContextFrame]] = defaultdict(list)
        for f in frames:
            if f.frame_type not in ("SYSTEM_PROMPT", "TOOL_DECLARATIONS"):
                frames_by_step[f.step_index].append(f)

        sorted_steps = sorted(frames_by_step.keys())
        if not sorted_steps:
            return ContextEvolutionReport(conversation_id=conversation_id)

        active_cats: dict[str, int] = {
            "system_instruction": system_tokens,
            "tool_declarations": tool_tokens,
            "compaction_summary": 0,
            "user_prompts": 0,
            "cot_reasoning": 0,
            "tool_outputs": 0,
            "assistant_responses": 0,
            "system_history": 0,
        }
        cumul_tokens = system_tokens + tool_tokens

        points: list[EvolutionStepPoint] = []

        for step in sorted_steps:
            step_frames = frames_by_step[step]
            is_ckpt = step in checkpoints_set

            if is_ckpt:
                # Reset active window to baseline when compaction boundary triggers
                active_cats = {
                    "system_instruction": system_tokens,
                    "tool_declarations": tool_tokens,
                    "compaction_summary": 0,
                    "user_prompts": 0,
                    "cot_reasoning": 0,
                    "tool_outputs": 0,
                    "assistant_responses": 0,
                    "system_history": 0,
                }

            step_delta = sum(f.est_tokens for f in step_frames)
            for f in step_frames:
                if f.category in active_cats:
                    active_cats[f.category] += f.est_tokens

            cumul_tokens += step_delta
            active_total = sum(active_cats.values())

            # Pick representative source & title for step
            source = step_frames[0].source if step_frames else ""
            frame_type = step_frames[0].frame_type if step_frames else ""
            title = step_frames[0].title if step_frames else f"Step {step}"

            points.append(
                EvolutionStepPoint(
                    step_index=step,
                    source=source,
                    frame_type=frame_type,
                    title=title,
                    delta_tokens=step_delta,
                    active_tokens=active_total,
                    cumulative_tokens=cumul_tokens,
                    is_checkpoint=is_ckpt,
                    breakdown=EvolutionBreakdown(
                        system_instruction=active_cats.get("system_instruction", 0),
                        tool_declarations=active_cats.get("tool_declarations", 0),
                        compaction_summary=active_cats.get("compaction_summary", 0),
                        user_prompts=active_cats.get("user_prompts", 0),
                        cot_reasoning=active_cats.get("cot_reasoning", 0),
                        tool_outputs=active_cats.get("tool_outputs", 0),
                        assistant_responses=active_cats.get("assistant_responses", 0),
                        system_history=active_cats.get("system_history", 0),
                    ),
                )
            )

        max_active = max((p.active_tokens for p in points), default=0)
        max_cumul = max((p.cumulative_tokens for p in points), default=0)

        return ContextEvolutionReport(
            conversation_id=conversation_id,
            total_steps=len(sorted_steps),
            checkpoints=checkpoints,
            max_active_tokens=max_active,
            max_cumulative_tokens=max_cumul,
            points=points,
        )


