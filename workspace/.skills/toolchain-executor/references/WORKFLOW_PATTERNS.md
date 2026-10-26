# Workflow Orchestration Patterns

Common patterns for coordinating specialist skills.

## 1. Linear Chain
The simplest pattern where Step A $\rightarrow$ Step B $\rightarrow$ Step C.
- **Use case**: Data extraction $\rightarrow$ Translation $\rightarrow$ Formatting.

## 2. Parallel Fan-out / Fan-in
Executing multiple independent tasks and aggregating their results.
- **Fan-out**: Requesting data from three different sources simultaneously.
- **Fan-in**: Summarizing the results of those three sources into one report.
- **Use case**: Market research across multiple competitors.

## 3. Conditional Branching (Router)
Choosing the next step based on the output of the current step.
- **Pattern**: If (Output == "Type A") $\rightarrow$ Skill A; Else $\rightarrow$ Skill B.
- **Use case**: Triage $\rightarrow$ Specialist Route.

## 4. Iterative Loop (Refinement)
Repeating a step until a certain quality threshold is met.
- **Pattern**: Execute $\rightarrow$ Validate $\rightarrow$ (If Fail) $\rightarrow$ Refine $\rightarrow$ Execute.
- **Use case**: Code generation $\rightarrow$ Unit Testing $\rightarrow$ Bug Fixing.

## 5. Compensation (Saga Pattern)
If a step fails late in the chain, execute "undo" actions for previous steps.
- **Use case**: Book Flight $\rightarrow$ Book Hotel $\rightarrow$ (Hotel Fails) $\rightarrow$ Cancel Flight.
