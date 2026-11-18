#!/usr/bin/env python
"""Load messages.json and generate a tagmemory database."""

import json
import sqlite3
import re
import sys
import os
from datetime import datetime

def load_messages(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def extract_tags_from_file(filepath):
    """Extract ```tag: ... ``` blocks from tagged.md file."""
    tags = {}
    with open(filepath, 'r') as f:
        content = f.read()
    pattern = r'```tag:\s*(\w+)\s*\n(.*?)```'
    for match in re.finditer(pattern, content, re.DOTALL):
        tag_name = match.group(1)
        tag_value = match.group(2).strip()
        tags[tag_name] = tag_value
    return tags

def extract_recall(content):
    """Extract ```recall: ... ``` markers."""
    recalls = []
    pattern = r'```recall:\s*(\w+)\s*```'
    for match in re.finditer(pattern, content):
        recalls.append(match.group(1))
    return recalls

def create_db(db_path):
    """Create SQLite database with schema."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Messages table
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        message_index INTEGER NOT NULL
    )''')
    
    # Tags table
    c.execute('''CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_name TEXT NOT NULL,
        tag_value TEXT NOT NULL,
        source_message INTEGER,
        FOREIGN KEY (source_message) REFERENCES messages(id)
    )''')
    
    # Recalls table
    c.execute('''CREATE TABLE IF NOT EXISTS recalls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recall_type TEXT NOT NULL,
        source_message INTEGER,
        FOREIGN KEY (source_message) REFERENCES messages(id)
    )''')
    
    # Metadata table
    c.execute('''CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        timestamp TEXT NOT NULL
    )''')
    
    conn.commit()
    return conn

def populate_db(conn, messages, tags_file=None):
    """Populate database with messages and extracted tags/recalls."""
    c = conn.cursor()
    
    # Clear existing data
    c.execute('DELETE FROM metadata')
    c.execute('DELETE FROM tags')
    c.execute('DELETE FROM recalls')
    c.execute('DELETE FROM messages')
    conn.commit()
    
    # Insert messages
    for i, msg in enumerate(messages):
        c.execute(
            'INSERT INTO messages (role, content, message_index) VALUES (?, ?, ?)',
            (msg['role'], msg['content'], i)
        )
    
    # Extract tags from tagged.md file if provided
    tags = {}
    if tags_file:
        tags = extract_tags_from_file(tags_file)
        for tag_name, tag_value in tags.items():
            c.execute(
                'INSERT INTO tags (tag_name, tag_value) VALUES (?, ?)',
                (tag_name, tag_value)
            )
    
    # Extract recalls from messages
    all_content = ' '.join(m['content'] for m in messages)
    recalls = extract_recall(all_content)
    for recall_type in recalls:
        c.execute(
            'INSERT INTO recalls (recall_type) VALUES (?)',
            (recall_type,)
        )
    
    # Insert metadata
    now = datetime.now().isoformat()
    c.execute(
        'INSERT INTO metadata (key, value, timestamp) VALUES (?, ?, ?)',
        ('message_count', str(len(messages)), now)
    )
    c.execute(
        'INSERT INTO metadata (key, value, timestamp) VALUES (?, ?, ?)',
        ('user_count', str(sum(1 for m in messages if m['role'] == 'user')), now)
    )
    c.execute(
        'INSERT INTO metadata (key, value, timestamp) VALUES (?, ?, ?)',
        ('assistant_count', str(sum(1 for m in messages if m['role'] == 'assistant')), now)
    )
    c.execute(
        'INSERT INTO metadata (key, value, timestamp) VALUES (?, ?, ?)',
        ('tag_count', str(len(tags)), now)
    )
    c.execute(
        'INSERT INTO metadata (key, value, timestamp) VALUES (?, ?, ?)',
        ('recall_count', str(len(recalls)), now)
    )
    
    conn.commit()

def main():
    # Configurable paths
    messages_file = 'messages.json'
    db_name = sys.argv[1] if len(sys.argv) > 1 else 'tagmemory.db'
    tags_file = sys.argv[2] if len(sys.argv) > 2 else 'All-star log tagged.md'
    
    print(f"Loading messages from {messages_file}...")
    messages = load_messages(messages_file)
    print(f"Loaded {len(messages)} messages")
    
    print(f"Creating database: {db_name}")
    conn = create_db(db_name)
    
    print("Populating database...")
    populate_db(conn, messages, tags_file)
    
    # Verify
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM messages')
    msg_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM tags')
    tag_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM recalls')
    recall_count = c.fetchone()[0]
    
    print(f"\nDatabase created successfully!")
    print(f"  Messages: {msg_count}")
    print(f"  Tags: {tag_count}")
    print(f"  Recalls: {recall_count}")
    
    # Show tags
    c.execute('SELECT tag_name, tag_value FROM tags')
    print("\nTags:")
    for tag_name, tag_value in c.fetchall():
        print(f"  {tag_name}: {tag_value[:50]}...")
    
    conn.close()

if __name__ == '__main__':
    main()
