# Work through GitHub

SmartNotice uses GitHub issues and a private Project to coordinate the coursework milestones. Pull requests keep changes to the shared branch reviewable while the local verification commands provide evidence for each change.

## Track work

Use the [SmartNotice Project](https://github.com/users/NgTHung/projects/2) and [repository issues](https://github.com/NgTHung/smartnotice/issues) for task scope and progress. Each roadmap issue has acceptance criteria and a course milestone. Calendar due dates and team assignments need information supplied by the team.

| Field | Meaning |
|---|---|
| Status | Todo, In Progress, or Done |
| Phase | Data, Models, Application, or Delivery |
| Priority | P0 for critical dependencies/deliverables, P1 for planned comparisons, P2 for optional work |
| Milestone | Week 6 data/EDA, Week 10 models/evaluation, or final application/submission |

Read the issue and its linked contract before starting. Set its status to In Progress when work begins. Close it and set Done when the acceptance criteria have evidence. Record actual human annotation and review outcomes; software checks cannot stand in for those activities.

## Merge changes

Create a descriptive task branch from `main`, commit one concern at a time, and open a pull request. Link its issue, describe the resulting behavior, and record the local checks appropriate to the change in [AGENTS.md](../AGENTS.md). Resolve review conversations before merging. Use a squash or rebase merge to preserve linear history.

`main` requires pull requests and resolved conversations. Its protection applies to administrators, blocks force pushes and deletion, and requires linear history. It requires zero approving reviews, so the owner can merge without a second collaborator. Revisit that count when the team has another reviewer.

CI workflows and required status checks are omitted by project choice. Run and report the relevant local verification before merging. Keep the privacy and staged-file review rules in AGENTS.md when publishing code, examples, or reports.
