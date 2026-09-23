"""Tests for Antigravity transcript and step parser."""

import pytest
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
