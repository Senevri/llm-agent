import os
import pytest
from run_ollama_agent_v2 import run_bash, read_file, write_file

def test_write_and_read_file():
    test_file = "/tmp/test_agent_file.txt"
    test_content = "Hello, this is a test content."
    
    # Test write_file
    write_result = write_file(test_file, test_content)
    assert "Successfully wrote" in write_result
    assert os.path.exists(test_file)
    
    # Test read_file
    read_result = read_file(test_file)
    assert read_result == test_content
    
    # Cleanup
    os.remove(test_file)

def test_read_nonexistent_file():
    result = read_file("/tmp/non_existent_file_12345.txt")
    assert "Error reading file" in result

def test_run_bash_success():
    # Simple command that always works
    result = run_bash("echo 'Hello World'")
    assert "Hello World" in result

def test_run_bash_failure():
    # Command that should fail (assuming /root is read-only or protected)
    result = run_bash("ls /root/forbidden_folder_xyz")
    assert "error" in result.lower() or "denied" in result.lower()

