#!/usr/bin/env python3
"""
Error Handling Best Practices
----------------------------

This script demonstrates best practices for error handling in Python,
including custom exceptions and proper use of try/except blocks.
"""

# Custom exception class
class InvalidInputError(Exception):
    """Custom exception for invalid input."""
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


# Function with proper error handling
def divide(a: float, b: float) -> float:
    """Divide two numbers and handle division by zero."""
    if b == 0:
        raise InvalidInputError("Cannot divide by zero.")
    return a / b


# Function with validation
def validate_age(age: int) -> None:
    """Validate that age is within a reasonable range."""
    if age < 0 or age > 120:
        raise InvalidInputError("Age must be between 0 and 120.")


# Example usage with try/except blocks
if __name__ == "__main__":
    # Example 1: Division with error handling
    try:
        result = divide(10, 2)
        print(f"Division result: {result}")
    except InvalidInputError as e:
        print(f"Error: {e}")
    
    try:
        result = divide(10, 0)
        print(f"Division result: {result}")
    except InvalidInputError as e:
        print(f"Error: {e}")
    
    # Example 2: Age validation
    try:
        validate_age(150)
    except InvalidInputError as e:
        print(f"Error: {e}")
    
    try:
        validate_age(30)
        print("Age is valid.")
    except InvalidInputError as e:
        print(f"Error: {e}")
    
    # Example 3: Using else and finally
    try:
        result = divide(10, 5)
    except InvalidInputError as e:
        print(f"Error: {e}")
    else:
        print(f"Success: {result}")
    finally:
        print("Operation completed.")