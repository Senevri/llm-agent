# Flowcharts and Process Diagrams

Use for workflows, procedures, branching logic, and decision trees.

## Plan first
1. Identify the start, end states, actions, and decisions.
2. Write the process as a sequence before drawing it.
3. Express decisions as clear questions with labelled outcomes (for example, Yes/No).
4. Identify loops and failure paths; include them only when they are part of the actual process.
5. Choose Mermaid for ordinary flows; use SVG only when a custom layout is necessary.

## Conventions
- Start/end: rounded terminator.
- Action: rectangle.
- Decision: diamond with labelled outgoing paths.
- Input/output: parallelogram if the notation needs it.
- Arrows show process direction; avoid relying on position alone to communicate direction.
- Keep the main path visually prominent and route exception paths clearly.
- Use consistent labels and avoid crossing arrows where possible.

## Verification
Trace each path from start to a valid end. Confirm each decision has its required branches, loops return to the correct point, and no step is accidentally disconnected. Validate Mermaid syntax when Mermaid is used.
