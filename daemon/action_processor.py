"""Action processor for the HAL9000 daemon."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ActionExtractor:
    """Extracts actions from agent responses and parses them into structured format."""
    
    def parse_response(self, response: str) -> tuple[str, list[dict[str, Any]]]:
        """Split response into text and actions.

        Actions are extracted from code blocks with language 'action' or specific markers.
        <thinking> and <reflection> tags are stripped from the returned text.
        """
        action_pattern = r"(`{1,3})action\s*\n([\s\S]*?)\n\1"
        matches = re.findall(action_pattern, response)

        actions = []
        for match in matches:
            # match is a tuple (backticks, content) due to two capture groups
            content = match[1]
            try:
                action = json.loads(content.strip())
                actions.append(action)
            except json.JSONDecodeError:
                pass

        text = re.sub(action_pattern, "", response).strip()
        text = re.sub(r"</?thinking>|</?reflection>", "", text).strip()
        return text, actions


def main() -> None:
    """Parse a sample response from stdin."""
    import sys
    
    response = sys.stdin.read()
    extractor = ActionExtractor()
    text, actions = extractor.parse_response(response)
    
    print(json.dumps({"text": text, "actions": actions}, indent=2))


if __name__ == "__main__":
    main()
