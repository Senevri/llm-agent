
from pathlib import Path
import sys

if not Path(__file__).parent.parent in sys.path:
    sys.path.append(str(Path(__file__).parent.parent))
from tools.agent_tools import *

def test_replace_lines():
    from pprint import pprint, pformat
    import json
    module_dir = Path(__file__).parent.parent
    if  not module_dir in sys.path:
        sys.path.append(str(module_dir))
    # print(pformat(TOOL_DEFINITIONS))
    # print(json.dumps(TOOL_DEFINITIONS, indent=2))

    test_file =(
"""
1: first line
2: second line
3: third line
4: Content---
5  asdfasdfasdfasdfsa
6 asdfasdfasdfasdfsa
7 asdfasdfasdfasdfsa
8 asdfasdfasdfasdfsa
9 asdfasdfasdfasdfsa
10 asdfasdfasdfasdfsa
""").strip() + "\n"

    import logging
    logger._logger.setLevel(logging.DEBUG)
    testfile_path = Path(__file__).parent / "test_file.txt"
    testfile_path.write_text(test_file)

    print(search_file(str(testfile_path), "second"))
    # Fails:
    try:
        res = replace_lines_in_file(testfile_path, ["new first line", "new second line"], 1, ["first line", "second line"])
        print(res)

        res = replace_lines_in_file(testfile_path, ["new first line", "new second line"], 1, ["1: first line", "2: second line"])
        print(res)

        res = replace_lines_in_file(testfile_path, ["5: this is better", "6: something"], 1,
                                    ["5  asdfasdfasdfasdfsa", "6 asdfasdfasdfasdfsa", "7 asdfasdfasdfasdfsa"])
        assert "lines do not match" in res
        print(res)
        res = replace_lines_in_file(testfile_path, ["7: this is better", "8: something", "9: something", "10: something"], 1,
                                    ["8 asdfasdfasdfasdfsa", "9 asdfasdfasdfasdfsa", "10 asdfasdfasdfasdfsa"])
        assert "lines do not match" in res
        print(res)
        res = replace_lines_in_file(testfile_path, ["5: this is better", "6: something"], 5,
                                    ["5  asdfasdfasdfasdfsa", "6 asdfasdfasdfasdfsa", "7 asdfasdfasdfasdfsa"])
        assert "Successfully replaced lines in" in res
        print(res)
        res = replace_lines_in_file(testfile_path, ["7: this is better", "8: something", "9: something", "10: something"], 7,
                                    ["8 asdfasdfasdfasdfsa", "9 asdfasdfasdfasdfsa", "10 asdfasdfasdfasdfsa"])
        assert "Successfully replaced lines in" in res
        print(res)
        res = replace_lines_in_file(testfile_path, ["just", "adding", "a", "bunch", "of", "lines"], 8,
                                    ["8: something"])
        print(res)
        assert "Successfully replaced lines in" in res
        print(res)
        print(read_file(str(testfile_path)))
    except Exception as e:
        print(e)
    finally:
        input("Press enter to delete test file")
        testfile_path.unlink()

if __name__ == "__main__":
    import logging
    logger._logger.setLevel(logging.DEBUG)

    test_replace_lines()