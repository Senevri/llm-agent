#!/usr/bin/env python3
"""
Modularity Example
-------------------

This script demonstrates modularity by organizing code into separate modules.
It simulates a project structure with a core module and a utility module.
"""

# Simulate importing modules from a project structure
# Assume the following structure:
# my_project/
# ├── src/
# │   ├── __init__.py
# │   ├── core/
# │   │   ├── __init__.py
# │   │   └── calculator.py
# │   └── utils/
# │       ├── __init__.py
# │       └── helpers.py

# Simulate the core/calculator.py module
class Calculator:
    """A simple calculator module."""
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b


# Simulate the utils/helpers.py module
def log_message(message):
    """Log a message to the console."""
    print(f"[LOG] {message}")

def validate_input(value, expected_type):
    """Validate that the input is of the expected type."""
    if not isinstance(value, expected_type):
        raise TypeError(f"Expected {expected_type}, got {type(value)}")
    return value


# Main script
if __name__ == "__main__":
    # Use the Calculator module
    calculator = Calculator()
    log_message("Running calculator operations...")
    
    # Validate inputs before using the calculator
    a = validate_input(10, int)
    b = validate_input(5, int)
    
    print(f"Addition: {calculator.add(a, b)}")
    print(f"Subtraction: {calculator.subtract(a, b)}")