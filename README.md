# HAL9000

Autonomous recursive reasoning agent research.

A sandboxed agent that maintains an ongoing inner monologue, thinks about whatever it finds meaningful, and produces tangible outputs — all running autonomously across weeks or longer.

## Architecture

```
One Docker container (network_mode: host, resource-limited)
┌───────────────────────────────────────┐
│  daemon/controller.py                  │
│    ↓ calls Ollama on localhost:11434   │
│    ↓ logs everything to /var/log/      │
│    ↓ executes actions in /workspace/   │
│    ↓ maintains state in /state/        │
│                                        │
│  agent/processor.py (unused stub)     │
└───────────────────────────────────────┘
```

Key design:
- **Tamper-proof logging**: The daemon is the only thing that calls Ollama and writes logs. The agent (LLM output) never touches its own trace.
- **Minimal surface**: Container has no public ports. Network is host-mode only to reach Ollama. No extra services.
- **Recursive**: Agent can read and analyze its own logs, build tools, maintain state — all autonomously.
- **Persistent**: Named Docker volumes survive restarts.

## Prerequisites

- Docker + Compose v2
- Local Ollama on `localhost:11434` with a model (e.g. `ollama pull qwen3`)

## Run

```
# Build and start the agent (detached)
./bin/start

# View status and recent logs
./bin/status

# Send a task
./bin/attach "Write a recursive function that explores the workspace"

# Stop the agent
./bin/stop

# Follow live logs
docker compose -f compose.yaml -p hal9000 logs -f hal9000
```

## Configuration

Set environment variables before `./bin/start`:

```
export HAL9000_MODEL=qwen3:32b          # Ollama model (default: qwen3:32b)
export HAL9000_MAX_HISTORY=50           # Recent turns in context
export HAL9000_LOOP_INTERVAL=5          # Seconds between turns
export HAL9000_AGENT_TIMEOUT=300        # Ollama timeout
```

## Files

- `daemon/controller.py` — Core loop: calls Ollama, logs, executes actions
- `daemon/config.py` — Configuration + agent preprompt
- `daemon/log_record.py` — Immutable log management (agent can't modify)
- `daemon/action_executor.py` — Executes agent actions in /workspace/
- `daemon/action_processor.py` — Parses ` ```action` blocks from LLM output
- `daemon/context_builder.py` — Builds prompt context from state + logs
- `agent/processor.py` — Stub for testing without Ollama (not used by default)
- `compose.yaml` — Single Docker service, host network, persistent volumes

## License

DSSL — Demerden Sie Sich License
