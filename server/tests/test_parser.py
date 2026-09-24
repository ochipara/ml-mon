import json
import pytest
from ml_mon.config import AntigravityConfig
from ml_mon.core.parser import ConversationParser
from ml_mon.core.models import Thought, ToolCall, ToolResult


def test_parse_step_record_user_input():
    parser = ConversationParser()
    raw = {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "status": "DONE",
        "created_at": "2026-09-23T18:41:41Z",
        "content": "<USER_REQUEST>\nShow me the logs\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime=now\n</ADDITIONAL_METADATA>",
    }
    step = parser.parse_step_record(raw)
    assert step.step_index == 0
    assert step.source == "USER_EXPLICIT"
    assert step.step_type == "USER_INPUT"
    assert step.user_prompt == "Show me the logs"
    assert step.thought is None


def test_parse_step_record_with_thought_and_tool_call():
    parser = ConversationParser()
    raw = {
        "step_index": 3,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "status": "DONE",
        "created_at": "2026-09-23T18:41:42Z",
        "thinking": "We need to view the file to check line 40.\nLet's view it now.",
        "tool_calls": [
            {
                "id": "call_123",
                "name": "view_file",
                "args": {
                    "AbsolutePath": "/path/to/file.py",
                    "StartLine": 1,
                    "EndLine": 50,
                    "toolAction": "Viewing file",
                    "toolSummary": "Check file contents",
                },
            }
        ],
    }
    step = parser.parse_step_record(raw)
    assert step.step_index == 3
    assert step.source == "MODEL"
    assert step.thought is not None
    assert "We need to view the file" in step.thought.content
    assert step.thought.preview == "We need to view the file to check line 40."
    assert len(step.tool_calls) == 1
    tc = step.tool_calls[0]
    assert tc.name == "view_file"
    assert tc.action == "Viewing file"
    assert tc.summary == "Check file contents"
    assert tc.args["AbsolutePath"] == "/path/to/file.py"


def test_parse_step_record_tool_result():
    parser = ConversationParser()
    raw = {
        "step_index": 4,
        "source": "MODEL",
        "type": "VIEW_FILE",
        "status": "DONE",
        "exit_code": 0,
        "content": "Line 1: def hello(): pass",
    }
    step = parser.parse_step_record(raw)
    assert step.step_index == 4
    assert step.tool_result is not None
    assert step.tool_result.tool_name == "VIEW_FILE"
    assert step.tool_result.content == "Line 1: def hello(): pass"
    assert step.tool_result.exit_code == 0


def test_extract_context_window(tmp_path):
    import json
    from ml_mon.config import AntigravityConfig

    # Create mock brain directory with transcript_full.jsonl
    conv_id = "test-session-123"
    log_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    transcript = log_dir / "transcript_full.jsonl"

    lines = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Initial prompt"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "First reasoning block", "tool_calls": []},
        {"step_index": 2, "source": "SYSTEM", "type": "CHECKPOINT", "content": "# Resuming from a compaction summary"},
        {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Post-compaction prompt"},
        {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "Active reasoning block", "tool_calls": [{"name": "run_command", "args": {"cmd": "ls"}}]},
        {"step_index": 5, "source": "MODEL", "type": "RUN_COMMAND", "content": "file1.txt\nfile2.txt"},
    ]

    with open(transcript, "w") as f:
        for r in lines:
            f.write(json.dumps(r) + "\n")

    cfg = AntigravityConfig(
        base_dir=tmp_path,
        conversations_dir=tmp_path / "conversations",
        brain_dir=tmp_path / "brain",
    )
    parser = ConversationParser(cfg)

    report = parser.extract_context_window(conv_id)
    assert report is not None
    assert report.conversation_id == conv_id
    assert report.has_compaction is True
    assert report.compaction_count == 1
    assert report.active_window_start_step == 2

    # Verify frame categorization & active status
    assert len(report.frames) == 7  # Step 4 has both COT and TOOL_CALL frames
    inactive_frames = [f for f in report.frames if not f.is_active]
    active_frames = [f for f in report.frames if f.is_active]

    assert len(inactive_frames) == 2  # Steps 0 and 1
    assert len(active_frames) == 5    # Steps 2, 3, 4 (COT + TOOL), 5

    # Check that compaction summary is present
    compaction_frames = [f for f in active_frames if f.frame_type == "CHECKPOINT"]
    assert len(compaction_frames) == 1
    assert compaction_frames[0].category == "compaction_summary"

    # Verify usage breakdown exists and contains categories
    categories = [b.category for b in report.breakdown]
    assert "compaction_summary" in categories
    assert "user_prompts" in categories
    assert "cot_reasoning" in categories
    assert "tool_outputs" in categories

    # Verify context evolution time-series
    assert report.evolution is not None
    assert report.evolution.conversation_id == conv_id
    assert report.evolution.checkpoints == [2]
    assert len(report.evolution.points) == 6
    p_ckpt = [p for p in report.evolution.points if p.is_checkpoint][0]
    assert p_ckpt.step_index == 2
    assert p_ckpt.breakdown.compaction_summary > 0
    assert report.evolution.max_active_tokens > 0


def test_model_name_extraction_with_decimal(tmp_path):
    conv_id = "test-model-conv"
    t_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    t_dir.mkdir(parents=True)
    transcript = t_dir / "transcript.jsonl"
    with open(transcript, "w") as f:
        f.write(json.dumps({
            "step_index": 0,
            "source": "USER_SETTINGS_CHANGE",
            "type": "USER_SETTINGS_CHANGE",
            "status": "DONE",
            "content": "Changed setting `Model Selection` from None to Gemini 3.8 Flash (Medium). No need to comment on this change if the user doesn't ask about it.",
        }) + "\n")
        f.write(json.dumps({
            "step_index": 1,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "content": "<USER_REQUEST>Hi</USER_REQUEST>",
        }) + "\n")

    cfg = AntigravityConfig(
        base_dir=tmp_path,
        conversations_dir=tmp_path / "conversations",
        brain_dir=tmp_path / "brain",
    )
    parser = ConversationParser(cfg)
    detail = parser.parse_conversation(conv_id)
    assert detail.summary.model_name == "Gemini 3.8 Flash (Medium)"
    assert detail.analytics.model_name == "Gemini 3.8 Flash (Medium)"


def test_extract_context_at_step(tmp_path):
    conv_id = "test-step-context"
    t_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    t_dir.mkdir(parents=True)
    transcript = t_dir / "transcript_full.jsonl"

    lines = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Initial prompt"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "First reasoning", "tool_calls": []},
        {"step_index": 2, "source": "SYSTEM", "type": "CHECKPOINT", "content": "# Resuming from compaction"},
        {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Second prompt"},
        {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "Second reasoning", "tool_calls": [{"name": "run_cmd", "args": {}}]},
    ]

    with open(transcript, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    cfg = AntigravityConfig(
        base_dir=tmp_path,
        conversations_dir=tmp_path / "conversations",
        brain_dir=tmp_path / "brain",
    )
    parser = ConversationParser(cfg)

    # Step 1 (before checkpoint): should have steps 0, 1
    rep_1 = parser.extract_context_at_step(conv_id, 1)
    assert rep_1 is not None
    assert rep_1.step_index == 1
    assert rep_1.active_window_start_step == 0
    assert len(rep_1.frames) == 2

    # Step 4 (after checkpoint at 2): should only include active steps (2, 3, 4)
    rep_4 = parser.extract_context_at_step(conv_id, 4)
    assert rep_4 is not None
    assert rep_4.step_index == 4
    assert rep_4.active_window_start_step == 2
    assert rep_4.is_compacted is True
    # Frame indices: Checkpoint (step 2), User input (step 3), CoT (step 4), Tool call (step 4)
    frame_steps = [f.step_index for f in rep_4.frames]
    assert 0 not in frame_steps
    assert 1 not in frame_steps
    assert 2 in frame_steps
    assert 3 in frame_steps
    assert 4 in frame_steps
    assert rep_4.total_active_tokens > 0
    assert "CONVERSATION TRAJECTORY" in rep_4.full_prompt_text


