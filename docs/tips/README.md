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
2. **Pass `--repo` to `gh`.** Write `gh issue view 12 --repo owner/name`. Without it, a command
   can act on the wrong repo.
3. **Check an issue number before a write.** `gh issue list --search` can return issues from other
   repos. Run `gh issue view <n> --repo owner/name --json title` before a comment or a label edit.
4. **Ask when the code and the docs disagree.** If a change contradicts a design doc, the agent
   stops and asks. It does not choose a side.
5. **Run the formatter on the whole repo before a commit.** If it changes files outside the task,
   put those changes in a separate `chore:` commit.
6. **Approve the plan before the code.** Use plan mode or a spec. Review the plan. Then let the
   agent build.
7. **Ask for a diagram.** A small diagram often explains a flow faster than a paragraph.
