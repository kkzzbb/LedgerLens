- Tasks are GitHub issues, one at a time
- Commit regularly

Roles

- PM - grooms a task before anyone implements it, follows docs/team/pm.md
- Engineer - implements one groomed task, follows docs/team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows docs/team/qa-engineer.md
- Accounting reviewer - checks financial issues before and after implementation, follows docs/team/accounting-reviewer.md

Financial rules

- Financial rules (rounding, aging, formulas, thresholds) are written
  in `docs/accounting-rules.md`
- Issues labelled `accounting-review` go through the Accounting
  reviewer twice: once after grooming and once after QA

Issues

- An issue is ready to implement when it follows `docs/task-template.md`
  and its "Depends on" issues are closed
- Issue numbers give the build order. Follow-up issues filed later
  (#76 and up) state where they fit through "Depends on"
- Build the vertical slice first. The MVP gate is #80: DemoBank → sync
  → database → dashboard, working end to end before the accounting
  features (#25 onward)
- A verification issue (#80, #75) adds no features. Gaps it finds are
  fixed in the issue that owns them, or filed as a new issue

Documents

- Documentation lives in `docs/`
- `docs/outdated/` holds the original plan, architecture and task list.
  They are still the reference for scope and decisions until they are
  replaced (#73)

Orchestrator

The main session is the orchestrator. It launches the PM, the engineer, QA, and Accounting Reviewer as subagents. It does not groom, implement or test itself.

Lifecycle

1. Pick the next open issue from the backlog
2. PM grooms it
3. Accounting reviewer checks the groomed issue (`accounting-review`
   label only). On FAIL, back to step 2 with the review comment as input
4. Engineer implements it
5. QA verifies it. On FAIL, back to step 4 with the QA comment as input
6. Accounting reviewer checks the implementation (`accounting-review`
   label only). On FAIL, back to step 4 with the review comment as input
7. Close the issue
8. Repeat until the backlog is empty

Rules

- One issue at a time
- Do not skip step 2, or steps 3 and 6 for labelled issues
- The engineer does not close the issue
- QA and the Accounting reviewer do not fix the code, they only output
  PASS or FAIL
- The orchestrator closes the issue only after QA outputs PASS and, for
  `accounting-review` issues, the Accounting reviewer outputs PASS on
  the implementation
