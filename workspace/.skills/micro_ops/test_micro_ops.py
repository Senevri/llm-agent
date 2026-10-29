import sys
import os
from implementation import TOOL_REGISTRY

def test_tools():
    print("--- Testing Micro-Ops Skill ---")
    
    # Get the directory where this test script is located
    base_dir = os.path.dirname(os.path.abspath(__file__))
    impl_path = os.path.join(base_dir, "implementation.py")
    
    # 1. Test grep
    print("Test grep (string): ", end="")
    assert TOOL_REGISTRY["grep"]("hello", "hello world") == "hello"
    assert TOOL_REGISTRY["grep"]("world", "hello world") == "world"
    assert TOOL_REGISTRY["grep"]("missing", "hello world") == "None"
    print("PASSED")

    print("Test grep (file): ", end="")
    test_file = os.path.join(base_dir, "test_grep.txt")
    with open(test_file, "w") as f:
        f.write("line one\nline two\nline three")
    assert TOOL_REGISTRY["grep"]("line (one|two|three)", test_file) == "line one\nline two\nline three"
    os.remove(test_file)
    print("PASSED")

    # 2. Test json_get
    print("Test json_get: ", end="")
    json_str = '{"user": {"name": "Alice", "age": 30}, "active": true}'
    assert TOOL_REGISTRY["json_get"]("user.name", json_str) == "Alice"
    assert TOOL_REGISTRY["json_get"]("user.age", json_str) == "30"
    assert TOOL_REGISTRY["json_get"]("user.nonexistent", json_str) == "None"
    print("PASSED")

    # 3. Test json_validate
    print("Test json_validate: ", end="")
    valid_json = '{"id": 1, "status": "ok"}'
    invalid_json = '{"id": 1}'
    assert TOOL_REGISTRY["json_validate"](valid_json, '["id", "status"]') == "Valid"
    assert TOOL_REGISTRY["json_validate"](invalid_json, '["id", "status"]') == "Missing: status"
    res = TOOL_REGISTRY["json_validate"]("not json", '["id"]')
    assert "Error:" in res
    print("PASSED")

    # 4. Test count
    print("Test count: ", end="")
    text = "hello world\nline two"
    assert TOOL_REGISTRY["count"]("lines", text) == "2"
    assert TOOL_REGISTRY["count"]("words", text) == "4"
    assert TOOL_REGISTRY["count"]("chars", text) == "20"
    print("PASSED")

    # 5. Test exists
    print("Test exists: ", end="")
    assert TOOL_REGISTRY["exists"](impl_path) == "True"
    assert TOOL_REGISTRY["exists"](os.path.join(base_dir, "non_existent_file_12345.txt")) == "False"
    print("PASSED")

    # 6. Test math
    print("Test math: ", end="")
    assert TOOL_REGISTRY["math"]("2 + 2") == "4"
    assert TOOL_REGISTRY["math"]("10 * 0.5") == "5.0"
    assert TOOL_REGISTRY["math"]("sqrt(16)") == "4.0"
    print("PASSED")

    # 7. Test shell_report
    print("Test shell_report: ", end="")
    stdout = "command output\nline 2\nline 3\nline 4\nline 5\nline 6"
    stderr = "some error\nmore error\nlast error"
    report = TOOL_REGISTRY["shell_report"](stdout, stderr, 1)
    assert "Status: FAILURE" in report
    assert "Exit Code: 1" in report
    assert "some error" in report
    assert "line 2" in report
    assert "line 6" in report
    print("PASSED")

    print("--- All Tests Passed! ---")

if __name__ == "__main__":
    test_tools()
