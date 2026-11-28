---
name: function-writer
description: Writes a single function, properly
compatibility:
metadata:
  version: "1.0.0"
  category: "software-dev"
---
# Function Writer

To write a function the right way.

## Instructions
 - Analyze the need for a function and what it should do.
 - Determine the inputs and outputs
 - Create a brief for writing the function as a task
 - write a test for the function
 - write a function that passes the test
 - ensure documentation


## Example:
```yaml
function: normalize_tag
module: tag_utils.py

purpose: Normalize a tag for consistent comparison.

inputs:
  tag: string

outputs:
  success: normalized string

errors:
  - empty input
  - non-string input

examples:
  passing:
    input: "  Python  "
    expected: "python"
  failing:
    input: ""
    expected_error: ValueError

constraints:
  - Do not modify the original input.
  - No external dependencies.

```