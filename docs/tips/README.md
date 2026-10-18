# Tips

How I work with AI coding agents, and why. Take what helps you.

| Page | Topic |
| --- | --- |
| [spec-driven-development.md](spec-driven-development.md) | Plan a change as a spec first. Then build it. |
| [writing-with-ste.md](writing-with-ste.md) | Make agents write short, clear text. |
| [other-tools.md](other-tools.md) | Use these skills in Copilot, Cursor, Codex, Gemini CLI, or claude.ai. |

## Habits that help

These come from real mistakes. Each one is a rule that I give my agent.

1. **Put repo facts in the repo.** Keep skills generic. Put branch names, test commands, and
   paths in the repo's `CLAUDE.md` or `AGENTS.md`. Then one skill works in many repos.
2. **Ask when the code and the docs disagree.** If a change contradicts a design doc, the agent
   stops and asks. It does not choose a side.
3. **Run the formatter on the whole repo before a commit.** If it changes files outside the task,
   put those changes in a separate `chore:` commit.
4. **Match the plan to the size of the change.** Plan a large change first: a new feature through
   many layers, a refactor, or a migration. Approve the plan before the code. Skip the plan for a
   small, clear change. The agent writes a decision log, and you read it in the PR. The workflow
   profile sets the plan form (see [framework/profiles/](../../framework/profiles/README.md)).
5. **Ask for a diagram.** A small diagram often explains a flow faster than a paragraph.
