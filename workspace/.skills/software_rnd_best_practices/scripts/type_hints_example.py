#!/usr/bin/env python3
"""
Type Hints and Static Typing Example
------------------------------------

This script demonstrates the use of type hints and static typing in Python
to improve code clarity and catch errors early.
"""

from typing import List, Optional, Dict, Union


# Function with type hints
def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


# Function with complex types
def process_items(items: List[str]) -> Dict[str, int]:
    """Process a list of strings and return a dictionary with counts."""
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


# Function with optional arguments
def find_item(items: List[str], search_term: Optional[str] = None) -> Union[str, None]:
    """Find an item in a list of strings."""
    if search_term is None:
        return None
    return search_term if search_term in items else None


# Class with type hints
class User:
    """A simple User class with type hints."""
    def __init__(self, name: str, age: int) -> None:
        self.name = name
        self.age = age

    def greet(self) -> str:
        return f"Hi, I'm {self.name} and I'm {self.age} years old."


# Example usage
if __name__ == "__main__":
    # Test the add function
    print(f"Addition: {add(2, 3)}")

    # Test the process_items function
    items = ["apple", "banana", "apple", "orange"]
    print(f"Item counts: {process_items(items)}")

    # Test the find_item function
    print(f"Found item: {find_item(items, 'banana')}")
    print(f"Found item: {find_item(items, 'grape')}")

    # Test the User class
    user = User("Alice", 30)
    print(user.greet())