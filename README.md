# HAL9000

Autonomous recursive reasoning agent research.

A sandboxed agent that maintains an ongoing inner monologue, thinks about whatever it finds meaningful, and produces tangible outputs — all running autonomously across weeks or longer.

## Architecture

```
HOST (outside Docker)              CONTAINER (resource-limited)
┌──────────────────────────┐       ┌────────────────────────┐
│  host/daemon.py          │       │  agent/processor.py    │
│    └─ Unix socket server │◄─────►│    └─ socket client    │
│    └─ calls Ollama       │  IPC  │    └─ builds context   │
│    └─ writes ./logs/     │       │    └─ executes actions │
│    └─ reads operator msgs│       └────────────────────────┘
│    └─ persists state     │                    │
└──────────────────────────┘                    ├─ writes to /workspace/
                                                ├─ runs shell commands
                                                └─ reads /state/
```

**Single point of control**: The host daemon is the only process that calls Ollama, writes logs to disk, and manages operator messages. The container agent is a thin executor that never touches Ollama or log files directly — all communication flows through a Unix socket.

Key design:
- **Tamper-proof logging**: The host daemon writes every entry to `./logs/` before any data reaches the container. The agent cannot modify, delete, or forge its own trace.
- **Minimal surface**: Container has no public ports, no host networking. The only host-to-container bridge is the Unix socket and shared workspace/state directories.
- **Recursive**: Agent can read and analyze its own log history (provided by the daemon in each turn), build tools, maintain state — all autonomously.
- **Persistent**: State survives restarts via `./state/state.json`. Logs accumulate in daily files under `./logs/`.

## Data Flow (one turn)

1. Agent connects to host daemon via Unix socket (`/tmp/hal9000/daemon.sock`)
2. Agent requests context → daemon returns preprompt + recent logs + operator messages
3. Agent builds prompt, sends `think` request → daemon calls Ollama, logs thought, returns response
4. Agent extracts ` ```action ` blocks, executes each action locally (write/run)
5. Agent sends action results to daemon via `log` → daemon persists to `./logs/actions/`
6. Loop

## Prerequisites

- Docker + Compose v2
- Python 3.10+ on host (for the host daemon)
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
```

## Configuration

Set environment variables before `./bin/start`:

```
export HAL9000_MODEL=qwen3:latest       # Ollama model (default: qwen3:latest)
export HAL9000_MAX_HISTORY=200          # Recent log entries in context
export HAL9000_LOOP_INTERVAL=5          # Seconds between turns
export HAL9000_AGENT_TIMEOUT=300        # Ollama timeout (seconds)
```

## Files

- `host/daemon.py` — Host daemon: Unix socket server, calls Ollama, writes logs
- `host/config.py` — Configuration + agent preprompt
- `host/logger.py` — Writes JSON-lines to `./logs/{category}/YYYY-MM-DD.log`
- `host/ollama_client.py` — Ollama API client (httpx)
- `agent/processor.py` — Container agent loop: connects to daemon, builds context, executes actions
- `daemon/context_builder.py` — Builds prompt context from state + logs (shared module)
- `daemon/action_executor.py` — Executes actions (write/run) inside the container
- `daemon/action_processor.py` — Parses ` ```action ` blocks from LLM output
- `daemon/log_record.py` — In-memory ring buffer (used for tests, not by the running daemon)
- `compose.yaml` — Single Docker service, socket-bound, no host network

## License

DSSL — Demerden Sie Sich License
