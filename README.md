# HAL9000

Autonomous recursive reasoning agent research.

A sandboxed agent that maintains an ongoing inner monologue, thinks about whatever it finds meaningful, and produces tangible outputs — all running autonomously across weeks or longer.

## How it works

```
┌─────────────────────────┐    ┌──────────────────────────┐
│  Host (daemon)          │    │  Docker container (agent)│
│                         │    │  (sandboxed, no network) │
│  loop_daemon ──→ Ollama │    │                          │
│                         │    │  agent/processor (dumb   │
│  (only caller with      │    │   stdin/stdout relay)    │
│   Ollama access)        │    │                          │
│  All actions & logs     │    │  Can read logs (RO)      │
│  managed by daemon      │    │  Can write /workspace/   │
└─────────────────────────┘    └──────────────────────────┘
```

Key design decisions:
- **Tamper-proof logging**: Agent never touches its own trace. The daemon calls Ollama, executes actions, and logs everything. Logs are on the host outside the container.
- **Minimal agent**: The agent process is a dumb stdin/stdout relay. No Ollama library, no network stack, no filesystem awareness beyond its sandbox.
- **Recursive**: Agent can read and analyze its own logs, build tools, maintain state — all autonomously.
- **Persistent**: Named Docker volumes survive restarts. Agent maintains its own state files.

## Prerequisites

- Docker + compose v2
- Local Ollama instance running on `localhost:11434` with a model loaded (e.g. `ollama pull qwen3`)
- Python 3.10+

## Run

```
# Start the agent (daemon + container, detached)
./bin/start

# View status
./bin/status

# Send a task to the agent
./bin/attach "Write a recursive function that explores the workspace"

# Stop the agent
./bin/stop

# Clear state and restart
./bin/reset
```

## Config

Set environment variables to customize:

```
HAL9000_MODEL=              # Ollama model (default: qwen3:32b)
HAL9000_MAX_HISTORY=        # Recent log entries included in context (default: 50)
HAL9000_LOOP_INTERVAL=      # Seconds between turns (default: 5)
HAL9000_AGENT_TIMEOUT=      # Ollama API timeout in seconds (default: 300)
HAL9000_START_TIME=         # Initial timestamp
```

## Files

- `daemon/controller.py` — The immortal controller. Calls Ollama, manages the loop.
- `agent/processor.py` — Dumb agent. stdin → response → stdout.
- `daemon/action_executor.py` — Executes agent actions on the host.
- `daemon/log_record.py` — Immutable log management.
- `daemon/config.py` — Configuration + agent preprompt.
- `compose.yaml` — Container networking + volumes.
- `pyproject.toml` — Dependencies + project config.

## License

DSSL (Do Source Code Source license)