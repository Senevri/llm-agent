#!/usr/bin/env python3
"""
Asynchronous Programming Example with asyncio
-------------------------------------------

This script demonstrates how to use asyncio for asynchronous programming
in Python, which is useful for I/O-bound tasks.
"""

import asyncio


# Asynchronous function
async def fetch_data(task_name: str, delay: int) -> str:
    """Simulate fetching data asynchronously."""
    print(f"Task {task_name} started")
    await asyncio.sleep(delay)  # Simulate I/O delay
    print(f"Task {task_name} completed")
    return f"Data from {task_name}"


# Main asynchronous function
async def main():
    """Run multiple asynchronous tasks concurrently."""
    # Create tasks
    task1 = asyncio.create_task(fetch_data("Task 1", 2))
    task2 = asyncio.create_task(fetch_data("Task 2", 1))
    task3 = asyncio.create_task(fetch_data("Task 3", 3))
    
    # Wait for tasks to complete
    results = await asyncio.gather(task1, task2, task3)
    
    # Print results
    for result in results:
        print(result)


# Example usage
if __name__ == "__main__":
    print("Running asynchronous tasks...")
    asyncio.run(main())