---
name: test-runner
description: Turn a testing goal into a practical checklist and status summary.
user-invocable: true
allowed-tools:
  - task_tools__make_checklist
  - task_tools__status_summary
  - task_tools__echo_task
---

When the user wants to test or validate work, use the task tools to turn that request into a short execution plan.

Recommended sequence:
1. Call `task_tools__echo_task` with the testing goal.
2. Call `task_tools__make_checklist` with the concrete checks to run.
3. After results are available, call `task_tools__status_summary`.

Keep the answer operational and ordered.

Testing focus: $ARGUMENTS
