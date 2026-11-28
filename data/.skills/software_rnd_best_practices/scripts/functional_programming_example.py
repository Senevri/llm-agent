#!/usr/bin/env python3
"""
Functional Programming Example
-------------------------------

This script demonstrates functional programming principles in Python:
- Pure functions
- Higher-order functions (map, filter, reduce)
- Immutability
"""

from functools import reduce


# Pure function: No side effects, same input always produces the same output
def square(x):
    """Return the square of a number."""
    return x * x


# Higher-order functions
numbers = [1, 2, 3, 4, 5]

# Using map to apply a function to each item in a list
squared_numbers = list(map(square, numbers))
print(f"Squared numbers: {squared_numbers}")

# Using filter to select items that meet a condition
def is_even(x):
    """Check if a number is even."""
    return x % 2 == 0

filtered_numbers = list(filter(is_even, numbers))
print(f"Even numbers: {filtered_numbers}")

# Using reduce to aggregate values
def multiply(a, b):
    """Multiply two numbers."""
    return a * b

product = reduce(multiply, numbers)
print(f"Product of numbers: {product}")

# Immutability: Avoid modifying existing data structures
original_list = [1, 2, 3]
new_list = original_list.copy()  # Create a copy to avoid modifying the original
new_list.append(4)

print(f"Original list (immutable): {original_list}")
print(f"Modified copy: {new_list}")

# Lambda functions for concise operations
double = lambda x: x * 2
print(f"Doubled numbers: {list(map(double, numbers))}")