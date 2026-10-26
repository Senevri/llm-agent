---
name: toolchain-executor
description: Manages multi-step agentic workflows by coordinating multiple specialized skills. Use this skill when a request requires a sequence of distinct actions (e.g., search -> analyze -> notify) where the output of one step serves as the input to the next. It acts as a conductor, maintaining state and handling transitions between specialist agents.
license: MIT
metadata:
  category: orchestration
  version: "1.0"
---

# Toolchain Executor

The Toolchain Executor is the management layer for complex tasks that cannot be solved by a single skill. It transforms a high-level goal into a structured sequence of tool/skill calls.

## Core Responsibilities

1. **Decomposition**: Break a complex request into a series of discrete, executable steps.
2. **State Management**: Capture the output of each step and format it for the next.
3. **Error Handling**: Detect failures in the chain and decide whether to retry, fallback, or abort.
4. **Orchestration**: Invoke the correct specialist skill for each step.

## Execution Workflow

1. **Analyze Goal**: Identify all required capabilities (skills).
2. **Define Chain**: Map the data flow (Step A Output $\rightarrow$ Step B Input).
3. **Execute Sequence**:
    - Call Skill 1 $\rightarrow$ Store Result.
    - Transform Result $\rightarrow$ Call Skill 2 $\rightarrow$ Store Result.
    - Repeat until goal is achieved.
4. **Final Synthesis**: Consolidate all step outputs into a final response for the user.

## Guidelines

- **Prefer Deterministic Chains**: When the sequence is known, define it explicitly.
- **Dynamic Routing**: If the next step depends on the previous output, use a conditional branch.
- **Validation**: Validate the output of each step before passing it to the next.

## References

- For state machine implementation details, see [STATE_MACHINE.md](references/STATE_MACHINE.md).
- For common orchestration patterns, see [WORKFLOW_PATTERNS.md](references/WORKFLOW_PATTERNS.md).
