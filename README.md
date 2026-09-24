# ml-mon (`gmon`)

A comprehensive real-time monitoring, visualization, and prompt reverse-engineering toolkit for Google Antigravity IDE sessions, featuring deep inspection of agent **Chain of Thought (CoT)**, tool executions, **Implementation Plans**, **Context Window Evolution**, and **Full Prompt Reconstruction**.

---

## ✨ Features

- 💬 **Live Timeline & CoT Stream**: Real-time SSE streaming of agent steps, internal reasoning thoughts, tool calls, execution outputs, and model responses.
- ⏱️ **Step Timing & Latency Analytics**: In-depth wall-clock timing breakdown, model thinking latency vs. tool execution time distribution, step duration waterfall chart, and per-tool performance benchmarks.
- 🌐 **Remote vs. Local Step Classification**: Clear visual distinction between remote LLM API inferences (`🌐 Remote` badge) and purely local IDE operations (user inputs, file executions, compactions).
- 🔍 **Point-in-Time Context Window Inspector**: Click any `🌐 Remote` badge or step to view the exact active context window, token breakdown, and reconstructed prompt passed to the agent at that step.
- 📈 **Context Window & Prompt Evolution Over Time**: Interactive stacked time-series vector chart displaying active context window sawtooths (compaction cliff drops) vs. cumulative session tokens with interactive crosshair scrubbing.
- 📄 **Full Prompt Reconstruction**: Complete reconstruction of base system identity, rules, skills/plugins catalogs, tool parameter schemas, and conversation trajectories directly from Antigravity storage.
- 📋 **Planning Documents & File Tracking**: Formatted viewing of `implementation_plan.md`, `walkthrough.md`, and real-time modified file tracking.
- ❓ **Architecture & Lifecycle Guide**: Built-in sequence diagrams and execution models explaining the turn-by-turn agent lifecycle.

---

## 📁 Project Layout

```
ml-mon/
├── README.md              # Project overview & quickstart
├── docs/                  # System documentation & specifications
│   ├── storage_formats.md # SQLite WAL schemas, JSONL logs, prompt reconstruction, and API reference
│   └── cli_usage.md       # CLI reference for `gmon`
├── server/                # Python 3.10+ engine, FastAPI server, & `gmon` CLI
│   ├── pyproject.toml
│   ├── src/ml_mon/        # Core models, scanner, parser, prompt reconstructor, and API
│   └── tests/             # Automated test suite (Pytest)
└── ui/                    # Web visualizer dashboard frontend (HTML5/CSS3/Vanilla JS)
```

---

## 🚀 Quick Start

### 1. Activate Conda Environment

```bash
conda activate ml-mon
```

*(Or create from scratch: `conda env create -f environment.yml`)*

### 2. Run the Visualizer Web Dashboard

```bash
# Start the real-time web visualizer (dashboard at http://127.0.0.1:8765)
gmon serve
```

### 3. Inspect Sessions from CLI

```bash
# List all sessions with live/idle status
gmon list

# View full timeline of latest session (including Chain of Thought)
gmon show latest

# Extract all Chain of Thought (reasoning) steps
gmon cot latest

# View implementation plan and walkthrough
gmon plan latest

# Inspect LLM context window, compaction boundary, and token usage breakdown
gmon context latest

# Export structured session data as JSON
gmon show latest --json
```

---

## 📚 Documentation

- [Storage Formats, Context Assembly, Token Estimation & API Reference](docs/storage_formats.md): Detailed reverse-engineering notes on SQLite WAL databases, protobuf snapshots, context window assembly, token estimation formulas, and REST endpoints.
- [CLI Reference](docs/cli_usage.md): Full command and flag reference for `gmon`.
