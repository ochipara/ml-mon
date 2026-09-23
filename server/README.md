# gmon (ml-mon server)

Python engine and CLI (`gmon`) for discovering, parsing, and streaming Antigravity IDE conversations, Chain of Thought (CoT), tool executions, and planning documents.

## Installation

```bash
cd server
pip install -e .
```

To include development dependencies:
```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# List all conversations
gmon list

# View the latest conversation with Chain of Thought (CoT) and tools
gmon show latest --cot --tools

# View a specific conversation by ID
gmon show <conversation-id> --cot

# Show only the implementation plan / walkthrough
gmon show latest --plan

# Export conversation as JSON
gmon show latest --json
```
