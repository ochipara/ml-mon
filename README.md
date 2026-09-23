# ml-mon (`gmon`)

A monitoring and visualization toolkit for Google Antigravity IDE sessions, featuring real-time inspection of agent **Chain of Thought (CoT)**, tool executions, and **Implementation Plans**.

## Project Layout

```
ml-mon/
├── README.md              # Project overview & quickstart
├── docs/                  # System documentation & specifications
│   ├── storage_formats.md # Antigravity SQLite schema & JSONL log specifications
│   └── cli_usage.md       # CLI reference for `gmon`
├── server/                # Python 3.10+ engine & `gmon` CLI
│   ├── pyproject.toml
│   ├── src/ml_mon/        # Core models, scanner, parser, and CLI
│   └── tests/             # Automated test suite
└── ui/                    # Web visualizer dashboard (Milestone 2)
```

## Quick Start

### 1. Activate Conda Environment

A dedicated conda environment `ml-mon` is configured with Python 3.12:

```bash
conda activate ml-mon
```

*(Alternatively, to create it from scratch on another machine: `conda env create -f environment.yml`)*

### 2. Inspect Antigravity Sessions with `gmon`

```bash
# List all sessions with live/idle status
gmon list

# View the full timeline of the latest session (including Chain of Thought)
gmon show latest

# Extract all Chain of Thought (reasoning) steps
gmon cot latest

# View the implementation plan and walkthrough
gmon plan latest

# Export structured session data as JSON
gmon show latest --json
```

## Documentation

- [Storage Formats & Schemas](docs/storage_formats.md): Detailed reverse-engineering notes on SQLite WAL databases and JSONL logs.
- [CLI Reference](docs/cli_usage.md): Full command and flag reference.
