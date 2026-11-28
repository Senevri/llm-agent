#!/usr/bin/env python3
"""
Pre-commit Hooks Example
-------------------------

This script demonstrates how to set up pre-commit hooks for code quality
checks using tools like `black`, `flake8`, and `mypy`.
"""

# Example .pre-commit-config.yaml file
pre_commit_config = """
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
        language_version: python3

  - repo: https://github.com/pycqa/flake8
    rev: 6.1.0
    hooks:
      - id: flake8
        additional_dependencies: [flake8-bugbear, flake8-docstrings]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: [types-requests]

  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks:
      - id: isort
"""

print("Example .pre-commit-config.yaml:")
print(pre_commit_config)

# Instructions for setting up pre-commit hooks
instructions = """
1. Install pre-commit:
   pip install pre-commit

2. Add the .pre-commit-config.yaml file to your project root.

3. Install the hooks:
   pre-commit install

4. Run the hooks manually:
   pre-commit run --all-files
"""

print("\nInstructions to set up pre-commit hooks:")
print(instructions)