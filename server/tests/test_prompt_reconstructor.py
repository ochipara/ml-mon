"""Unit tests for PromptReconstructor and prompt extraction."""

from ml_mon.config import AntigravityConfig
from ml_mon.core.prompt_reconstructor import PromptReconstructor, ProtobufReader


def test_protobuf_reader_varint():
    data = b"\x08\xac\x02"
    val, pos = ProtobufReader.parse_varint(data, 0)
    assert val == 8
    val2, pos2 = ProtobufReader.parse_varint(data, 1)
    assert val2 == 300


def test_prompt_reconstructor_fallback(tmp_path):
    # Test fallback to transcript when DB is absent
    conv_id = "test-conv-no-db"
    t_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    t_dir.mkdir(parents=True)
    import json
    with open(t_dir / "transcript.jsonl", "w") as f:
        f.write(json.dumps({
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "content": "Hello agent",
        }) + "\n")

    cfg = AntigravityConfig(
        base_dir=tmp_path,
        conversations_dir=tmp_path / "conversations",
        brain_dir=tmp_path / "brain",
    )
    rec = PromptReconstructor(cfg)
    prompt = rec.reconstruct(conv_id)
    assert prompt is not None
    assert prompt.conversation_id == conv_id
    assert len(prompt.sections) == 1
    assert prompt.sections[0].category == "conversation_history"
    assert "Hello agent" in prompt.sections[0].content
