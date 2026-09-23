# gmon CLI Usage Guide

`gmon` is the command-line interface for inspecting and monitoring Antigravity IDE conversations, agent Chain of Thought (CoT), tool calls, and planning documents.

## Installation

```bash
cd server
pip install -e .
```

## Commands

### 1. Launch Web Visualizer (`gmon serve`)
Starts the local web server and automatically opens the interactive dashboard in your browser:
```bash
# Start server on default http://127.0.0.1:8765 and open browser
gmon serve

# Custom port or host
gmon serve --port 9000 --host 0.0.0.0

# Start without automatically opening browser
gmon serve --no-open
```

### 2. List Conversations (`gmon list`)
Lists all conversations found in Antigravity storage:
```bash
# List recent 20 conversations
gmon list

# List all conversations
gmon list -n 0

# List only actively running sessions
gmon list --active

# Output as JSON
gmon list --json
```

### 2. Show Conversation Details (`gmon show`)
Displays the complete chronological conversation history, including user requests, Chain of Thought reasoning, tool calls, and final responses:
```bash
# View the most recent conversation
gmon show latest

# View a specific conversation by ID or prefix
gmon show e676e994-48cd-4f6c-8fd9-e1d3d12371a2

# Hide tool executions to focus only on CoT and messages
gmon show latest --no-tools

# Hide CoT to see only user prompts and tool results
gmon show latest --no-cot

# Display the implementation plan and walkthrough
gmon show latest --plan

# Output full structured data as JSON
gmon show latest --json
```

### 3. View Chain of Thought Only (`gmon cot`)
Convenient shortcut to inspect all internal reasoning steps in chronological order:
```bash
# Show all thoughts from the latest conversation
gmon cot latest

# Show thoughts for a specific conversation
gmon cot <conversation-id>
```

### 4. View Planning Documents (`gmon plan`)
Displays the formatted `implementation_plan.md` and `walkthrough.md` for a session:
```bash
# Show plan for latest conversation
gmon plan latest

# Show plan for a specific conversation
gmon plan <conversation-id>
```
