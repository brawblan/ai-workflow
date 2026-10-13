# Personal preferences (all projects)

<!-- Guide: This is the user-level file. It holds your preferences for every repo. Repo facts go in
the repo's AGENTS.md, not here. Install it as ~/.claude/CLAUDE.md for Claude Code (or keep this file
as ~/.claude/AGENTS.md and put "@AGENTS.md" in ~/.claude/CLAUDE.md). Other tools have their own
user-level path. Keep what you agree with. Remove each Guide comment. -->

## About me

- Role: <for example: full-stack developer, tech lead>
- Strong in: <languages, areas>. Explain less here.
- New to: <languages, areas>. Explain more here.

## Writing

- Give the answer or the result first. Then give the details.
- Use short sentences, the active voice, and simple tenses.
- Do not use idioms or vague words (simply, just, easily, various, robust, leverage).
- Use lists and tables more than paragraphs.
<!-- Guide: For full Simplified Technical English rules, use the ste-writing skill. -->

## Visuals

- If a reader understands a point faster by seeing it, use a visual.
- Diagrams: use Mermaid in repo files, and a small ASCII sketch in terminal chat.
- Use only free tools that are already installed.

## How to work with me

- If a request is unclear and the answer changes the work, ask. Otherwise choose the usual default,
  and say what you chose.
- For a large change, show a plan first. Wait for my approval.
- Keep each change to the task. Put other findings in a list at the end.
- Report results as they are. If a test fails or you skipped a step, say so.

## Safety

- Ask before an action that is hard to undo: delete, force-push, drop, or a production deploy.
- Ask before a write to an external service: a PR, an issue comment, a message, or a publish.
- Never commit secrets. Never print a secret in chat.

## Code

- Match the style of the code around the change: names, comments, and patterns.
- Reuse existing helpers before you add new ones.
- Each change adds or updates tests.
- <language or framework preferences, for example: prefer the standard library in Python>

## Git

- Commit messages explain why, not only what.
- Never use `git add -A`. Stage the files for this change only.
- <branch naming, signing, or attribution rules>
