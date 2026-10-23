# Use these skills in other tools

The skills use the open [Agent Skills](https://agentskills.io) format: a folder with a `SKILL.md`
file. Many AI coding tools can read this format. The folder path is different in each tool.

## Coding agents (Copilot, Cursor, Codex, Gemini CLI, and others)

1. Find your tool's skills folder in its docs. Many tools read `.agents/skills/` in a project.
2. Copy one folder from [`plugins/cornerstone/skills/`](../../plugins/cornerstone/skills/) into it.
   Copy the whole folder, not only `SKILL.md`. Some skills have a `references/` folder.
3. Restart the tool, and ask it to list its skills.

If your tool does not load skills, paste the `SKILL.md` text into the chat. Then give the task.

Not all tools load all parts of a skill in the same way. Test a skill before you depend on it.

## Instructions file (AGENTS.md)

[`global/AGENTS.md`](../../global/AGENTS.md) has my writing and visuals rules. Many tools read an
`AGENTS.md` file in the repo root. Copy the parts you want into yours.

Claude Code reads `CLAUDE.md`, not `AGENTS.md`. To use one file for both, put this line in
`CLAUDE.md`:

```
@AGENTS.md
```

## claude.ai (chat)

- **Skills:** Zip one skill folder. Upload it in claude.ai settings, in the skills section.
- **Rules:** Paste `global/AGENTS.md` into a Project's instructions, or into your profile
  preferences.

## Other chat tools

Paste a `SKILL.md` or `AGENTS.md` into the tool's custom instructions. The skills that run `git`
and `gh` need a coding agent with shell access. The `ste-writing` skill works in any chat.
