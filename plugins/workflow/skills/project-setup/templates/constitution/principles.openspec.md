# Principles

The principles live in [`openspec/config.yaml`](../openspec/config.yaml), in the `context` block.

OpenSpec copies `context` into each artifact that it makes. So the agent always has the rules, and it
does not need to read another file. One copy prevents drift.

- **Read them:** open `openspec/config.yaml`, and read the `## Principles (MUST)` section.
- **Amend them:** edit `context` in a PR. The version rules are in the comment at the top of the file.
- **Limit:** OpenSpec ignores all of `context` above 50 KB. Keep detail in the other constitution files.
