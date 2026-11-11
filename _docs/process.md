- Tasks are GitHub issues, one at a time
- Commit regularly

Roles

- PM - grooms a task before anyone implements it, follows _docs/team/pm.md
- Engineer - implements one groomed task, follows _docs/team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows _docs/team/qa-engineer.md
- Accounting reviewer - checks financial issues before and after implementation, follows _docs/team/accounting-reviewer.md

Flow

- PM grooms → Accounting reviewer checks the issue (financial issues
  only) → Engineer implements → QA → Accounting reviewer checks the
  implementation (financial issues only) → close
- A FAIL at any step sends the issue back to the step before it
- Financial rules (rounding, aging, formulas, thresholds) are written
  in `_docs/accounting-rules.md`

Issues

- An issue is ready to implement when it follows `_docs/task-template.md`
  and its "Depends on" issues are closed
- Issue numbers give the build order. Follow-up issues filed later
  (#76 and up) state where they fit through "Depends on"
- Build the vertical slice first. The MVP gate is #80: DemoBank → sync
  → database → dashboard, working end to end before the accounting
  features (#25 onward)
- A verification issue (#80, #75) adds no features. Gaps it finds are
  fixed in the issue that owns them, or filed as a new issue

Documents

- Documentation lives in `_docs/`
- `_docs/outdated/` holds the original plan, architecture and task list.
  They are still the reference for scope and decisions until they are
  replaced (#73)

Orchestrator

The main session is the orchestrator. It launches the PM, the engineer, QA, and Accounting Reviewer as subagents. It does not groom, implement or test itself.

Lifecycle

1. Pick the next open issue from the backlog
2. PM grooms it
3. Engineer implements it
4. QA verifies it
5. On FAIL, back to step 3 with the QA comment as input
6. On PASS, close the issue
7. Repeat until the backlog is empty

Rules

- One issue at a time
- Do not skip step 2
- The engineer does not close the issue
- QA does not fix the code, only outputs PASS or FAIL
- The orchestrator closes the issue only after QA outputs PASS