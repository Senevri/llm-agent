import json
import sys

def validate_workflow_json(json_text):
    """
    Validates if a workflow definition contains the required fields:
    - steps: A list of steps.
    - Each step must have an 'id' and a 'skill'.
    """
    try:
        data = json.loads(json_text)
        if "steps" not in data or not isinstance(data["steps"], list):
            return False, "Missing 'steps' list."
        
        for i, step in enumerate(data["steps"]):
            if "id" not in step or "skill" not in step:
                return False, f"Step {i} is missing 'id' or 'skill'."
        
        return True, "Valid workflow JSON."
    except json.JSONDecodeError:
        return False, "Invalid JSON format."

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 validate_workflow.py '<json_string>'")
        sys.exit(1)
    
    success, message = validate_workflow_json(sys.argv[1])
    print(message)
    sys.exit(0 if success else 1)
