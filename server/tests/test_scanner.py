"""Tests for conversation scanner and metadata extraction."""

from pathlib import Path
from ml_mon.config import AntigravityConfig
from ml_mon.core.scanner import ConversationScanner


def test_scanner_with_mock_directory(tmp_path: Path):
    base_dir = tmp_path / "antigravity-ide"
    convs_dir = base_dir / "conversations"
    brain_dir = base_dir / "brain"
    convs_dir.mkdir(parents=True)
    brain_dir.mkdir(parents=True)

    # Create dummy conversation 1 (sqlite only)
    (convs_dir / "conv_1.db").touch()

    # Create dummy conversation 2 (brain only)
    c2_brain = brain_dir / "conv_2"
    c2_logs = c2_brain / ".system_generated" / "logs"
    c2_logs.mkdir(parents=True)
    (c2_logs / "transcript_full.jsonl").write_text(
        '{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","content":"<USER_REQUEST>\\nBuild a visualization tool\\n</USER_REQUEST>"}\n'
    )

    config = AntigravityConfig(
        base_dir=base_dir,
        conversations_dir=convs_dir,
        brain_dir=brain_dir,
    )
    scanner = ConversationScanner(config)
    ids = scanner.list_conversation_ids()
    assert set(ids) == {"conv_1", "conv_2"}

    summaries = scanner.scan_all()
    assert len(summaries) == 2
    c2_summary = next(s for s in summaries if s.id == "conv_2")
    assert c2_summary.title == "Build a visualization tool"
    assert c2_summary.has_transcript is True
