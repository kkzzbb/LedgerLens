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
