# State Machine for Toolchain Execution

To ensure reliability in multi-step workflows, the Toolchain Executor utilizes a formal state machine approach.

## State Definitions

- **IDLE**: Waiting for a task.
- **PLANNING**: Decomposing the goal into a DAG (Directed Acyclic Graph) of steps.
- **EXECUTING**: Currently running a specific step in the chain.
- **VALIDATING**: Checking if the output of the last step meets the prerequisites for the next.
- **ERROR**: A step failed; determining recovery path.
- **COMPLETED**: Final goal achieved.

## Transitions

| From | To | Trigger |
| --- | --- | --- |
| IDLE | PLANNING | User Request Received |
| PLANNING | EXECUTING | Plan Validated |
| EXECUTING | VALIDATING | Tool/Skill Output Received |
| VALIDATING | EXECUTING | Validation Success $\rightarrow$ Next Step |
| VALIDATING | ERROR | Validation Failure |
| EXECUTING | ERROR | Exception/Timeout |
| ERROR | EXECUTING | Recovery Action Applied |
| ERROR | COMPLETED | Unrecoverable Error (with partial result) |
| VALIDATING | COMPLETED | All steps finished successfully |

## State Persistence

The state should be persisted in a structured format (e.g., JSON) to allow for resumption after failure:

```json
{
  "workflow_id": "wf-123",
  "current_state": "EXECUTING",
  "current_step": 2,
  "context": {
    "step_1_output": "...",
    "global_variables": {}
  },
  "history": [
    {"step": 1, "status": "success", "timestamp": "..."}
  ]
}
```
