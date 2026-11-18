#!/usr/bin/env python
"""Query the tagmemory database."""

import sqlite3
import sys

def query_db(db_path='tagmemory.db'):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Show all tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in c.fetchall()]
    print(f"Tables in {db_path}: {', '.join(tables)}")
    
    # Show message counts
    c.execute('SELECT role, COUNT(*) FROM messages GROUP BY role')
    print("\nMessages by role:")
    for role, count in c.fetchall():
        print(f"  {role}: {count}")
    
    # Show tags
    c.execute('SELECT tag_name, tag_value FROM tags')
    print("\nTags:")
    for tag_name, tag_value in c.fetchall():
        print(f"  {tag_name}: {tag_value}")
    
    # Show recalls
    c.execute('SELECT recall_type FROM recalls')
    print("\nRecalls:")
    for recall in c.fetchall():
        print(f"  {recall[0]}")
    
    # Show metadata
    c.execute('SELECT * FROM metadata')
    print("\nMetadata:")
    for key, value, timestamp in c.fetchall():
        print(f"  {key}: {value}")
    
    conn.close()

if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'tagmemory.db'
    query_db(db_path)
