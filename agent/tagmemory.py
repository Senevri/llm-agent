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
```update: mytag``` updates the message TODO: Could either update or could keep revison history.
The llm/user can use
markdown-style tagging to add a tag to a message.


The tag can be used to retrieve the message later.

The magic:
an LLM sends a message with a a tag. After the message is x steps from the HEAD
it gets replaced by the tag.
If the LLM needs to recall a message, it can use the tag to recall it.
However, again, over time the recalled memory gets replaced by the tag.


"""
import secrets
import time
from typing import Dict, Optional
import yaml
from pathlib import Path

import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Tag:
    def __init__(self, name, value):
        self.name = name
        self.id = f"#{secrets.token_hex(8)}-{time.time()}"
        self.value = value
        self.gist = None # Gist get generated offline
        self.archived = False



class TagMemory:
    def __init__(self):
        self.tags:Dict[str, Tag] = {}
        self.gists:Dict[str, str] = {} # is this needed?
        self.forget_tasks = []

    def load(self, path:Path):
        # format? JSON? YAML?
        if path.exists():
            self.tags = yaml.safe_load(open(path, encoding="utf-8"))

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

    def save(self, path:Path):
        # format? JSON? YAML?
        serializable_tags = self._serialize()
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(serializable_tags, f)

        except Exception as e:
            print(f"Failed to save tags: {e}")

    def add(self, tag, value):
        self.tags[tag] = Tag(tag, value)

    def get(self, tag)->Optional[Tag]:
        return self.tags.get(tag, None)

    def update(self, tag, value):
        self.tags[tag].value = value

    def forget(self, tag):
        self.tags[tag].archived = True

    def process_messages(self, messages:list, idx_pct:int=0):
        """ Memo to me:
        "messages": [
        { "role": "system", "content": "You are a helpful assistant." },
        { "role": "user", "content": "Hello!" }
        ]
        """
        # TODO: How to handle multiple tags in same content?
        # NOTE: Index runs from oldest to newest.
        message_count = len(messages)
        logger.info(f"Processing {message_count} messages.")
        for index, message in enumerate(messages):
            # Not our concern
            # if index < 2 or message.get("role") in ["system"]:
            #     continue
            short_msg = str(message)[:40]
            logger.debug(f"Index: {index} Message: {short_msg}")
            content = message.get('content', message.get("reasoning", ""))
            name = message.get("role")
            logger.debug(f"{name} Content: {content}")
            for tagtype in ["tag", "recall", "forget", "update"]:
                if f"```{tagtype}:" in content:
                    split_content = content.split(f"```{tagtype}:")
                    tag_memory = split_content[1].split("```")[0]
                    # Gets us the tagname. and more.
                    components = tag_memory.split("\n")
                    logger.debug(f"Components: {components} Count: {len(components)}")
                    if len(components) > 1:
                        # We have a message
                        tag = components[0].strip()
                        rest = "\n".join(components[1:]).strip()
                        #We have a body
                        logger.debug(f"Tag: {tag} Rest: {rest}")
                        if tag not in self.tags.keys():
                            logger.debug(f"Inserting tag {tag}")
                            self.add(tag, rest)
                        else:
                            if tagtype == "update":
                                self.update(tag, rest)
                            if tagtype == "tag":
                                tag_obj = self.get(tag)
                                if tag_obj:
                                    if (index / message_count)*100 < idx_pct:
                                        tag_obj.archived = True # Automatically forget
                                    if tag_obj.archived:
                                        tagtype="forget" #fallthough
                            if tagtype == "forget":
                                self.forget(tag)
                                self.forget_tasks.append(tag)
                            continue # tagged and bagged already. Q: When should it be removed
                    else:
                        tag = tag_memory
                        logger.debug("Tag Memory: %s", tag_memory)
                        if tag and tag in self.tags:
                            tag = tag_memory
                        if tagtype == "recall":
                            # Need to replace tag type too
                            messages[index]["content"] = message["content"].replace(split_content[0],
                                split_content[0].replace("```recall:", "```tag:")
                            )
                            tag_object = self.get(tag)
                            if tag_object:
                                messages[index]["content"] = message["content"].replace(tag_memory, tag_object.value)
                            # No need to process closed tag
        if self.forget_tasks:
            logger.info(f"Forgetting {len(self.forget_tasks)} tags: {self.forget_tasks}.")
            archived_tags = [tag for tag in self.tags.values() if tag.archived]
            for m in messages:
                for t in archived_tags:
                    name = t.name
                    parts = m["content"].split(f"```tag:{name}:")
                    if len(parts) < 2:
                        continue
                    part_a=parts[0].rstrip()
                    part_b = parts[1].split("```")[1].lstrip()
                    m["content"] = part_a + part_b
        self.save(Path("tags.yaml"))
        return messages

    def __str__(self):
        serializable_tags = self._serialize()
        return yaml.safe_dump(serializable_tags, default_flow_style=False, sort_keys=False, allow_unicode=True)

if __name__=="__main__":
    from pprint import pprint
    logger.setLevel(logging.DEBUG)
    test_file = r"E:\docker\llm-agent\workspace\repl_messages\repl_messages-20261103_013834.yaml"
    messages = yaml.safe_load(open(test_file, encoding="utf-8")) or []
    def generate_test_message(content):
        return {
            "role": "assistant",
            "content": content
        }

    test_input = [generate_test_message(f"""
    ```tag: mytag
    This is a test tag.
    ```
    """), ]

    for i in range(10):
        test_input.append(generate_test_message(f"""
        ```update: mytag
        This is a test tag updated.
        ```
        """))
    messages = test_input
    messages.extend(test_input)

    tm = TagMemory()
    messages = tm.process_messages(messages, 50)
    # print(yaml.dump(messages, default_flow_style=False))

    tm.save(Path("tags.yaml"))
    print(tm)
    forgetter = [generate_test_message(f"""
    ```forget: mytag
    This is a test tag.
    ```
    """), ]
    messages.extend(forgetter)
    messages = tm.process_messages(messages, 50)
    pprint(messages)
    pprint(tm)
    #yaml
    """' mytag': !!python/object:__main__.Tag
    archived: false
    gist: null
    id: '#387096c82571470f-1794302749.8954852'
    name: ' mytag'
    value: "    This is a test tag.\n    "
    """