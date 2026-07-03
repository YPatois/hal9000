"""Agent-side processor for HAL9000."""
from __future__ import annotations

import sys
from datetime import datetime


def main() -> None:
    """Process input and generate response."""
    context = sys.stdin.read()
    
    turn_match = "unknown"
    if "SYSTEM TURN: " in context and "\n\n" in context:
        turn_part = context.split("SYSTEM TURN: ")[1].split("\n")[0]
        try:
            turn_match = int(turn_part.strip())
        except ValueError:
            turn_match = "unknown"
    
    response = (
        f"[Agent Turn {turn_match}] Context received.\n\n"
        "```action\n"
        "{\n"
        '  "type": "write",\n'
        '  "path": "/workspace/status.txt",\n'
        '  "content": "Processing turn %s at %s"\n'
        "}\n"
        "```\n\n[Thought] I will monitor my environment."
    ) % (turn_match, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    print(response)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
