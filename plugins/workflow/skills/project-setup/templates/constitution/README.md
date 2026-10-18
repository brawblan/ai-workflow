# Constitution

The constitution is the small set of documents that every plan and every change must agree with.
Agents read it during spec-driven development (SDD). People read it to learn what the project is,
what it uses, and where it goes next.

| File | Owns | Read it when |
| --- | --- | --- |
| [mission.md](mission.md) | Vision, audience, tone, scope, and non-goals | You write a proposal, or you decide if work is in scope. |
| [personas.md](personas.md) | The users: who they are, their job stories, their limits, and the evidence | You shape a ticket, map acceptance criteria to job stories, or write acceptance tests. |
| [principles.md](principles.md) | The MUST rules for all changes | Always. <!-- Guide: If the repo uses OpenSpec, write: "Always. OpenSpec copies them into each artifact." --> |
| [tech-stack.md](tech-stack.md) | Approved technology, ownership, deploy limits, and quality gates | You write a design, or you add a dependency. |
| [roadmap.md](roadmap.md) | Phases and milestones, in order | You choose the next work, or you write a proposal. |

How to work in the repo (commands, branches, PRs) is in [AGENTS.md](../AGENTS.md), not here.

## Rules

- Each concept has one owner file. Link to it. Do not copy it.
- Change the constitution only in a PR. Say which file changed and why.
- If a change contradicts the constitution, stop. Change the constitution first, or change the plan.
