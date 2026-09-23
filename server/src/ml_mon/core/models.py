"""Structured data models for conversations, steps, Chain of Thought, plans, and analytics."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class Thought(BaseModel):
    """Agent Chain of Thought (internal reasoning)."""

    step_index: int
    created_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    content: str = Field(description="Raw markdown thinking process")

    @property
    def preview(self) -> str:
        """First line or truncated snippet of the thinking."""
        lines = [line.strip() for line in self.content.splitlines() if line.strip()]
        return lines[0] if lines else ""

    @property
    def character_count(self) -> int:
        return len(self.content)


class ToolCall(BaseModel):
    """Invocation of an agent tool."""

    call_id: Optional[str] = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    action: Optional[str] = None
    summary: Optional[str] = None


class ToolResult(BaseModel):
    """Result of a tool execution."""

    step_index: int
    tool_name: Optional[str] = None
    status: str = "DONE"
    exit_code: Optional[int] = None
    content: Optional[str] = None
    truncated: bool = False
    duration_seconds: Optional[float] = None


class StepRecord(BaseModel):
    """A single step in the conversation trajectory."""

    step_index: int
    source: str = Field(description="USER_EXPLICIT, MODEL, SYSTEM, etc.")
    step_type: str = Field(description="USER_INPUT, PLANNER_RESPONSE, VIEW_FILE, etc.")
    status: str = "DONE"
    created_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    is_checkpoint: bool = False
    is_error: bool = False
    thought: Optional[Thought] = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_result: Optional[ToolResult] = None
    user_prompt: Optional[str] = None
    model_response: Optional[str] = None
    raw_content: Optional[str] = None


class UserEnvironment(BaseModel):
    """IDE context and state captured during user prompt."""

    active_document: Optional[str] = None
    cursor_line: Optional[int] = None
    open_documents: list[str] = Field(default_factory=list)
    running_commands: list[str] = Field(default_factory=list)
    model_name: Optional[str] = None


class FileModification(BaseModel):
    """File modified or created during session."""

    path: str
    operation: str = Field(description="create, modify, replace")
    step_index: int
    tool_name: str


class MediaArtifact(BaseModel):
    """Visual media or task log produced in session."""

    name: str
    path: str
    relative_url: str
    media_type: str = Field(description="image, video, log")
    size_bytes: int = 0
    modified_at: Optional[str] = None


class SessionAnalytics(BaseModel):
    """Aggregated session analytics, tool counts, and IDE context."""

    model_name: Optional[str] = None
    total_thoughts: int = 0
    total_thinking_chars: int = 0
    tool_counts: dict[str, int] = Field(default_factory=dict)
    error_count: int = 0
    checkpoint_count: int = 0
    touched_files: list[FileModification] = Field(default_factory=list)
    environment: Optional[UserEnvironment] = None
    media_artifacts: list[MediaArtifact] = Field(default_factory=list)


class PlanAsset(BaseModel):
    """Planning documents and walkthroughs."""

    plan_path: Optional[str] = None
    plan_content: Optional[str] = None
    plan_last_modified: Optional[str] = None
    walkthrough_path: Optional[str] = None
    walkthrough_content: Optional[str] = None
    walkthrough_last_modified: Optional[str] = None


class ConversationSummary(BaseModel):
    """Summary metadata for a conversation."""

    id: str
    title: str = "Untitled Session"
    created_at: Optional[str] = None
    last_modified: Optional[str] = None
    step_count: int = 0
    is_active: bool = False
    has_plan: bool = False
    has_walkthrough: bool = False
    has_sqlite: bool = False
    has_transcript: bool = False
    model_name: Optional[str] = None


class ConversationDetail(BaseModel):
    """Complete detail of a conversation including all steps, CoTs, plans, and analytics."""

    summary: ConversationSummary
    steps: list[StepRecord] = Field(default_factory=list)
    thoughts: list[Thought] = Field(default_factory=list)
    plan: Optional[PlanAsset] = None
    analytics: Optional[SessionAnalytics] = None


class ContextFrame(BaseModel):
    """A distinct message frame within the LLM context window."""

    index: int
    step_index: int
    source: str = "UNKNOWN"
    frame_type: str = Field(description="USER_INPUT, CHECKPOINT, COT, TOOL_CALL, TOOL_RESULT, ASSISTANT, etc.")
    category: str = Field(description="compaction_summary, user_prompts, cot_reasoning, tool_outputs, assistant_responses, system_history")
    title: str
    char_count: int
    est_tokens: int
    is_active: bool = True
    preview: str
    full_content: str


class UsageBreakdown(BaseModel):
    """Token and character utilization for a specific component category."""

    category: str
    label: str
    char_count: int = 0
    est_tokens: int = 0
    percentage: float = 0.0


class ContextWindowReport(BaseModel):
    """Comprehensive report on the LLM's active and historical context window."""

    conversation_id: str
    active_window_start_step: int = 0
    has_compaction: bool = False
    compaction_count: int = 0
    total_active_chars: int = 0
    total_active_tokens: int = 0
    total_session_chars: int = 0
    total_session_tokens: int = 0
    breakdown: list[UsageBreakdown] = Field(default_factory=list)
    frames: list[ContextFrame] = Field(default_factory=list)

