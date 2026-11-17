#!/usr/bin/env python
"""Load messages, close tags (replace recalls with values), and print for comparison."""

import json
import sys
from pathlib import Path
from tagmemory import TagMemory, Tag
from tagmemory_loader import extract_tags_from_file
import sqlite3

def load_messages(json_path: str) -> list:
    """Load messages from JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_tags_from_db(db_path: str) -> TagMemory:
    """Load tags from SQLite database."""
    tagmemory = TagMemory()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT tag_name, tag_value FROM tags')
    for tag_name, tag_value in c.fetchall():
        tag = Tag(name=tag_name, value=tag_value)
        tagmemory.tags[tag_name] = tag
    conn.close()
    return tagmemory

def load_tags_from_markdown_file(md_path: str) -> TagMemory:
    """Load tags from tagged markdown file."""
    tagmemory = TagMemory()
    tags = extract_tags_from_file(md_path)
    for tag_name, tag_value in tags.items():
        tag = Tag(name=tag_name, value=tag_value)
        tagmemory.tags[tag_name] = tag
    return tagmemory

def print_messages_with_closed_tags(messages: list, tagmemory: TagMemory,
                                    max_chars: int = 200, show_diff: bool = True):
    """Print messages with tags closed (recalls replaced with values)."""
    print("=" * 80)
    print("MESSAGES WITH TAGS CLOSED")
    print("=" * 80)

    recall_marker = chr(96)*3 + 'recall:'

    for i, msg in enumerate(messages):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')

        # Check if this message has recalls
        has_recalls = recall_marker in content

        if has_recalls:
            print(f"\n{'='*80}")
            print(f"MESSAGE {i} ({role}) - HAS RECALLS")
            print(f"{'='*80}")

            # Show original
            print("\n--- ORIGINAL ---")
            #print(content[:max_chars])
            print(content)
            if len(content) > max_chars:
                print(f"... ({len(content) - max_chars} more chars)")

            # Process the message to close tags
            processed = tagmemory.process_messages([msg], 0)
            processed_content = processed[0].get('content', '')

            # Show processed
            print("\n--- PROCESSED (TAGS CLOSED) ---")
            print(processed_content)
            #print(processed_content[:max_chars])
            if len(processed_content) > max_chars:
                print(f"... ({len(processed_content) - max_chars} more chars)")

            # Show diff if requested
            if show_diff:
                print("\n--- DIFF ---")
                orig_lines = content.split('\n')
                proc_lines = processed_content.split('\n')

                for j, (orig, proc) in enumerate(zip(orig_lines, proc_lines)):
                    if orig != proc:
                        print(f"Line {j}:")
                        print(f"  ORIG:  {orig[:100]}")
                        print(f"  PROC:  {proc[:100]}")

                if len(orig_lines) != len(proc_lines):
                    print(f"Line count differs: {len(orig_lines)} vs {len(proc_lines)}")
        else:
            # Just print a summary for messages without recalls
            tag_marker = chr(96)*3 + 'tag:'
            forget_marker = chr(96)*3 + 'forget:'
            update_marker = chr(96)*3 + 'update:'

            has_tags = tag_marker in content
            has_forgets = forget_marker in content
            has_updates = update_marker in content

            if has_tags or has_forgets or has_updates:
                print(f"\n{'='*80}")
                print(f"MESSAGE {i} ({role}) - HAS TAGS/OPERATIONS")
                print(f"{'='*80}")
                print(f"Content (first {max_chars} chars):")
                print(content[:max_chars])
                if len(content) > max_chars:
                    print(f"... ({len(content) - max_chars} more chars)")

def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else 'messages.json'
    db_path = sys.argv[2] if len(sys.argv) > 2 else 'tagmemory.db'
    md_path = sys.argv[3] if len(sys.argv) > 3 else 'All-star log tagged.md'

    print(f"Loading messages from: {json_path}")
    messages = load_messages(json_path)
    print(f"Loaded {len(messages)} messages")

    print(f"\nLoading tags from database: {db_path}")
    tagmemory = load_tags_from_db(db_path)
    print(f"Loaded {len(tagmemory.tags)} tags: {list(tagmemory.tags.keys())}")

    print(f"\nLoading tags from markdown: {md_path}")
    tagmemory_md = load_tags_from_markdown_file(md_path)
    print(f"Loaded {len(tagmemory_md.tags)} tags: {list(tagmemory_md.tags.keys())}")

    # Compare tags
    print("\n=== TAG COMPARISON ===")
    db_tags = set(tagmemory.tags.keys())
    md_tags = set(tagmemory_md.tags.keys())

    print(f"Database tags: {sorted(db_tags)}")
    print(f"Markdown tags: {sorted(md_tags)}")

    if db_tags == md_tags:
        print("✓ Tags match!")
    else:
        print(f"✗ Tags differ!")
        print(f"  In DB only: {db_tags - md_tags}")
        print(f"  In MD only: {md_tags - db_tags}")

    # Print messages with closed tags
    print_messages_with_closed_tags(messages, tagmemory)

    # Also print a summary of all tags
    print("\n=== ALL TAGS ===")
    for name, tag in tagmemory.tags.items():
        print(f"{name}: {tag.value[:100]}...")

if __name__ == '__main__':
    main()
