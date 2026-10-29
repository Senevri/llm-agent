#!/usr/bin/env python3
"""
TDD Example: Testing a Calculator Class
---------------------------------------

This script demonstrates Test-Driven Development (TDD) by testing a simple
Calculator class. It follows the red-green-refactor cycle:
1. Write a failing test (red).
2. Write minimal code to pass the test (green).
3. Refactor the code while keeping tests passing.
"""

import pytest


# Step 1: Write a failing test (red)
def test_add():
    """Test the add method of the Calculator class."""
    calculator = Calculator()
    assert calculator.add(2, 3) == 5


def test_subtract():
    """Test the subtract method of the Calculator class."""
    calculator = Calculator()
    assert calculator.subtract(5, 3) == 2


def test_multiply():
    """Test the multiply method of the Calculator class."""
    calculator = Calculator()
    assert calculator.multiply(4, 5) == 20


def test_divide():
    """Test the divide method of the Calculator class."""
    calculator = Calculator()
    assert calculator.divide(10, 2) == 5


def test_divide_by_zero():
    """Test division by zero raises an exception."""
    calculator = Calculator()
    with pytest.raises(ValueError):
        calculator.divide(10, 0)


# Step 2: Write minimal code to pass the tests (green)
class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b

    def multiply(self, a, b):
        return a * b

    def divide(self, a, b):
        if b == 0:
            raise ValueError("Cannot divide by zero.")
        return a / b


# Step 3: Run the tests to ensure they pass
if __name__ == "__main__":
    pytest.main([__file__, "-v"])