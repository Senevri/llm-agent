#!/usr/bin/env python3
import os
import sys
import yaml

def validate_skill(skill_path):
    if not os.path.isdir(skill_path):
        print(f"Error: {skill_path} is not a directory")
        return False

    skill_md_path = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md_path):
        print(f"Error: {skill_md_path} not found")
        return False

    with open(skill_md_path, 'r') as f:
        content = f.read()

    if not content.startswith('---'):
        print("Error: SKILL.md must start with YAML frontmatter '---'")
        return False

    try:
        # Split frontmatter and body
        parts = content.split('---', 2)
        if len(parts) < 3:
            print("Error: SKILL.md must have a closing '---' for frontmatter")
            return False
        
        frontmatter = yaml.safe_load(parts[1])
        if not frontmatter:
            print("Error: Frontmatter is empty")
            return False

        # Validate name
        name = frontmatter.get('name')
        if not name:
            print("Error: 'name' field is required in frontmatter")
            return False
        
        if len(name) > 64 or len(name) < 1:
            print("Error: 'name' must be between 1 and 64 characters")
            return False
        
        if not all(c.islower() or c.isdigit() or c == '-' for c in name):
            print("Error: 'name' must contain only lowercase letters, numbers, and hyphens")
            return False
        
        if name.startswith('-') or name.endswith('-'):
            print("Error: 'name' must not start or end with a hyphen")
            return False
        
        if '--' in name:
            print("Error: 'name' must not contain consecutive hyphens")
            return False

        # Validate description
        description = frontmatter.get('description')
        if not description:
            print("Error: 'description' field is required in frontmatter")
            return False
        
        if len(description) > 1024 or len(description) < 1:
            print("Error: 'description' must be between 1 and 1024 characters")
            return False

        print(f"Skill '{name}' is valid.")
        return True

    except Exception as e:
        print(f"Error parsing frontmatter: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: validate_skill.py <skill_path>")
        sys.exit(1)
    
    success = validate_skill(sys.argv[1])
    sys.exit(0 if success else 1)
