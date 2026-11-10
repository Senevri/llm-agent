#!/usr/bin/python
"""
Idea:
This interacts with a list of messages. The llm/user can use
markdown-style tagging to add a tag to a message.
The tag can be used to retrieve the message later.

Example:

```tag: mytag
This is a message with a tag.
```
```recall: mytag``` gets replaced with the message, if it exists
```forget: mytag``` forgets the message from messages, but not tag memory
```update: mytag``` updates the message TODO: Could either update or could keep revision history.

The tag can be used to retrieve the message later.

The magic:
an LLM sends a message with a tag. After the message is x steps from the HEAD
it gets replaced by the tag.
If the LLM needs to recall a message, it can use the tag to recall it.
However, again, over time the recalled memory gets replaced by the tag.
"""
import re
import secrets
import time
from typing import Dict, Optional, Any, List, Tuple
import yaml
from pathlib import Path

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Tag:
    def __init__(self, name: str, value: str):
        self.name = name
        self.id = f"#{secrets.token_hex(8)}-{time.time()}"
        self.value = value
        self.gist: Optional[str] = None  # Gist generated offline
        self.archived: bool = False

    def __repr__(self) -> str:
        return f"Tag(name={self.name!r}, value={self.value!r}, archived={self.archived})"


class MarkdownTagParser:
    """
    Robust parser for markdown-style tag blocks in message content.

    Supported syntax:
    - ```tag: name\nvalue```  — create a tag
    - ```recall: name```      — recall a tag value (replaced with value)
    - ```forget: name```      — forget/archive a tag
    - ```update: name\nvalue``` — update a tag value

    This class handles:
    - Flexible tag names (alphanumeric, hyphens, dots, underscores)
    - Values on same line or next line
    - Multiple occurrences in a single message
    - Proper position tracking for replacements
    """

    # Patterns for each tag type
    # Tag name: alphanumeric, hyphens, dots, underscores (no \w+ limitation)
    TAG_NAME = r'[\w][\w.\-]*'

    PATTERNS = {
        'tag':      rf'```tag:\s*({TAG_NAME})\s*(?:\n(.*?))?\s*```',
        'recall':   rf'```recall:\s*({TAG_NAME})\s*```',
        'forget':   rf'```forget:\s*({TAG_NAME})\s*(?:\n(.*?))?\s*```',
        'update':   rf'```update:\s*({TAG_NAME})\s*(?:\n(.*?))?\s*```',
    }

    def __init__(self):
        self.compiled = {
            name: re.compile(pattern, re.DOTALL | re.IGNORECASE)
            for name, pattern in self.PATTERNS.items()
        }

    def find_all(self, content: str, tag_type: str) -> List[Tuple[str, Optional[str], int, int]]:
        """
        Find all occurrences of a tag type in content.

        Returns list of (tag_name, value_or_none, start, end) tuples.
        """
        pattern = self.compiled[tag_type]
        results = []
        for match in pattern.finditer(content):
            tag_name = match.group(1)
            value = match.group(2) if match.lastindex >= 2 else None
            results.append((tag_name, value, match.start(), match.end()))
        return results

    def replace_all(self, content: str, tag_type: str,
                    replacer: callable) -> str:
        """
        Replace all occurrences of a tag type in content.

        Args:
            content: The original content string
            tag_type: One of 'tag', 'recall', 'forget', 'update'
            replacer: Function(tag_name, value, start, end) -> replacement_string

        The replacer function receives the match details and returns
        the replacement string. If the replacer returns None, the
        original match is preserved.
        """
        matches = self.find_all(content, tag_type)
        if not matches:
            return content

        # Process matches in reverse order to preserve positions
        result = content
        for tag_name, value, start, end in reversed(matches):
            replacement = replacer(tag_name, value, start, end)
            if replacement is not None:
                result = result[:start] + replacement + result[end:]

        return result

    def process_tag(self, content: str, tag_memory: 'TagMemory',
                    is_old: bool) -> str:
        """Process all ```tag: name\nvalue``` blocks."""
        def replacer(tag_name, value, start, end):
            tag_memory.add(tag_name, value or '')
            if is_old:
                tag_memory.forget(tag_name)
            return None  # Keep original in message

        return self.replace_all(content, 'tag', replacer)

    def process_recall(self, content: str, tag_memory: 'TagMemory') -> str:
        """Process all ```recall: name``` blocks, replacing with tag value.

        Tags that were explicitly forgotten (in forget_tasks) are NOT recalled.
        Tags that are merely archived (via is_old auto-archive) ARE still recalled.
        """
        def replacer(tag_name, value, start, end):
            tag_obj = tag_memory.get(tag_name)
            if tag_obj and tag_name not in tag_memory.forget_tasks:
                return tag_obj.value
            return None  # Keep original if tag not found or explicitly forgotten

        return self.replace_all(content, 'recall', replacer)

    def process_forget(self, content: str, tag_memory: 'TagMemory') -> str:
        """Process all ```forget: name``` blocks, adding to forget_tasks."""
        def replacer(tag_name, value, start, end):
            if tag_memory.forget(tag_name):
                tag_memory.forget_tasks.append(tag_name)
            return None  # Keep original in message

        return self.replace_all(content, 'forget', replacer)

    def process_update(self, content: str, tag_memory: 'TagMemory') -> str:
        """Process all ```update: name\nvalue``` blocks."""
        def replacer(tag_name, value, start, end):
            if value is not None:
                tag_memory.update(tag_name, value)
            return None  # Keep original in message

        return self.replace_all(content, 'update', replacer)


class TagMemory:
    def __init__(self):
        self.tags: Dict[str, Tag] = {}
        self.gists: Dict[str, str] = {}  # is this needed?
        self.forget_tasks: list = []
        self.parser = MarkdownTagParser()

    def load(self, path: Path):
        """Load tags from a YAML file. Reconstructs Tag objects from serialized dicts."""
        if path.exists():
            data = yaml.safe_load(open(path, encoding="utf-8"))
            if isinstance(data, list):
                self.tags = {}
                for item in data:
                    if isinstance(item, dict) and "name" in item:
                        tag = Tag(
                            name=item["name"],
                            value=item.get("value", ""),
                        )
                        tag.id = item.get("id", tag.id)
                        tag.gist = item.get("gist", None)
                        tag.archived = item.get("archived", False)
                        self.tags[tag.name] = tag
            else:
                logger.warning(f"Expected list in YAML file {path}, got {type(data).__name__}")

    def _serialize(self) -> list:
        return [
            {
                "id": tag.id,
                "name": tag.name,
                "value": tag.value,
                "gist": tag.gist,
                "archived": tag.archived
            }
            for tag in self.tags.values()
        ]

    def save(self, path: Path):
        """Save tags to a YAML file."""
        serializable_tags = self._serialize()
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(serializable_tags, f)
        except Exception as e:
            print(f"Failed to save tags: {e}")

    def add(self, tag_name: str, value: str):
        """Add a new tag. Overwrites if tag already exists."""
        self.tags[tag_name] = Tag(tag_name, value)

    def get(self, tag_name: str) -> Optional[Tag]:
        """Get a tag by name."""
        return self.tags.get(tag_name, None)

    def update(self, tag_name: str, value: str) -> bool:
        """Update an existing tag. Returns True if tag existed."""
        if tag_name in self.tags:
            self.tags[tag_name].value = value
            return True
        return False

    def forget(self, tag_name: str) -> bool:
        """Archive a tag. Returns True if tag existed."""
        if tag_name in self.tags:
            self.tags[tag_name].archived = True
            return True
        return False

    def process_messages(self, messages: list, idx_pct: int = 0) -> list:
        """Process messages for tag operations (tag, recall, forget, update).

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            idx_pct: Percentage threshold for auto-archiving tags.
                     Messages before this percentage get auto-archived.

        Returns:
            Modified messages list.
        """
        message_count = len(messages)
        logger.info(f"Processing {message_count} messages.")

        for index, message in enumerate(messages):
            # Only process assistant messages for tag operations
            role = message.get('role', '')
            if role != 'assistant':
                continue

            content = message.get('content', message.get("reasoning", ""))
            if not content:
                continue

            # Calculate if this message is "old" enough to be auto-archived
            is_old = (index / message_count) * 100 < idx_pct

            # Process each tag type sequentially using the robust parser
            new_content = self.parser.process_tag(content, self, is_old)
            new_content = self.parser.process_recall(new_content, self)
            new_content = self.parser.process_forget(new_content, self)
            new_content = self.parser.process_update(new_content, self)

            messages[index]["content"] = new_content

        # Handle global forget cleanup if needed
        if self.forget_tasks:
            logger.info(f"Forgetting {len(self.forget_tasks)} tags: {self.forget_tasks}.")
            # Remove ```tag: ...``` blocks from messages for archived tags
            for m in messages:
                for tag_name in self.forget_tasks:
                    marker = f"```tag:{tag_name}:"
                    if marker in m["content"]:
                        parts = m["content"].split(marker)
                        if len(parts) > 1:
                            # Remove the tag block
                            close_idx = parts[1].find("```")
                            if close_idx != -1:
                                m["content"] = parts[0] + parts[1][close_idx:]
                            else:
                                m["content"] = parts[0]

        self.save(Path("tags.yaml"))
        return messages


    def process_messages_xml(self, messages: list, idx_pct: int = 0) -> list:
        """Process messages for tag operations using XML-style tags.

        Syntax:
        - <tag name>Value</tag>
        - <recall name>
        - <forget name>
        - <update name>Value</update>
        """
        message_count = len(messages)
        logger.info(f"Processing {message_count} messages.")

        for index, message in enumerate(messages):
            content = message.get('content', message.get("reasoning", ""))
            if not content:
                continue

            is_old = (index / message_count) * 100 < idx_pct
            new_content = content

            # 1. Process <tag name>Value</tag>
            # Pattern: <tag\s+(\w+)>(.*?)</tag>
            def replace_tag(match):
                tag_name = match.group(1)
                value = match.group(2).strip()
                self.add(tag_name, value)
                if is_old:
                    self.forget(tag_name)
                return match.group(0) # Keep the tag in the message for now

            new_content = re.sub(r'<tag\s+(\w+)>(.*?)</tag>', replace_tag, new_content, flags=re.DOTALL)

            # 2. Process <update name>Value</update>
            def replace_update(match):
                tag_name = match.group(1)
                value = match.group(2).strip()
                self.update(tag_name, value)
                return match.group(0) # Keep the update tag in the message

            new_content = re.sub(r'<update\s+(\w+)>(.*?)</update>', replace_update, new_content, flags=re.DOTALL)

            # 3. Process <recall name>
            def replace_recall(match):
                tag_name = match.group(1)
                tag_obj = self.get(tag_name)
                if tag_obj:
                    return tag_obj.value
                else:
                    return match.group(0) # Keep the recall tag if not found

            new_content = re.sub(r'<recall\s+(\w+)>', replace_recall, new_content)

            # 4. Process <forget name>
            def replace_forget(match):
                tag_name = match.group(1)
                if self.forget(tag_name):
                    self.forget_tasks.append(tag_name)
                return "" # Remove the forget tag from the message

            new_content = re.sub(r'<forget\s+(\w+)>', replace_forget, new_content)

            messages[index]["content"] = new_content

        # Cleanup: Remove <tag name>...</tag> blocks for forgotten tags
        if self.forget_tasks:
            logger.info(f"Forgetting {len(self.forget_tasks)} tags: {self.forget_tasks}.")
            for m in messages:
                for tag_name in self.forget_tasks:
                    # Remove the entire tag block
                    pattern = rf'<tag\s+{re.escape(tag_name)}>.*?</tag>'
                    m["content"] = re.sub(pattern, "", m["content"], flags=re.DOTALL)

        self.save(Path("tags.yaml"))
        return messages
    def __str__(self) -> str:
        serializable_tags = self._serialize()
        return yaml.safe_dump(serializable_tags, default_flow_style=False, sort_keys=False, allow_unicode=True)


if __name__ == "__main__":
    from pprint import pprint
    logger.setLevel(logging.DEBUG)

    test_file = r"E:\docker\llm-agent\workspace\repl_messages\repl_messages-20261103_013834.yaml"
    messages = yaml.safe_load(open(test_file, encoding="utf-8")) or []

    def generate_test_message(content):
        return {
            "role": "assistant",
            "content": content
        }

    test_input = [generate_test_message("""
    ```tag: mytag
    This is a test tag.
    ```
    """)]

    for i in range(10):
        test_input.append(generate_test_message("""
        ```update: mytag
        This is a test tag updated.
        ```
        """))
    messages = test_input
    messages.extend(test_input)

    tm = TagMemory()
    messages = tm.process_messages(messages, 50)

    tm.save(Path("tags.yaml"))
    print(tm)

    forgetter = [generate_test_message("""
    ```forget: mytag
    This is a test tag.
    ```
    """)]
    messages.extend(forgetter)
    messages = tm.process_messages(messages, 50)
    pprint(messages)
    pprint(tm)
