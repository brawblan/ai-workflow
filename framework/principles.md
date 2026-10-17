# Principles

Version: 0.1.0 (draft). Each principle has a rule, a reason, the evidence, and how to enforce it.
Evidence IDs point to the [dossier](../docs/research/dossier.md).

The words MUST, SHOULD, and MAY have the meanings in RFC 2119.

## Summary

| ID | Principle | One-line rule |
| --- | --- | --- |
| P1 | Checks decide | Deterministic checks, not agent claims, decide if work is done. |
| P2 | Separate the writer from the judge | The actor (human or agent) that writes code does not write its tests or approve it. |
| P3 | Judgment goes into the inputs | A human makes the ticket good. Then the prompt can be simple. |
| P4 | Context is a budget | Load the minimum. Load the rest only when a task needs it. |
| P5 | Each component earns its place | Each rule, skill, role, and hook has an eval, an owner, and a review date. |
| P6 | Enforce what you can state | If a rule can be a check, make it a check. |
| P7 | Ceremony scales with risk | The profile sets the plan form and the gates. |
| P8 | Small units, fresh sessions, state in files | One unit of work per session. Durable state lives in versioned files. |
| P9 | Bounded autonomy | Least privilege. A human approves each destructive action. |
| P10 | Volume is a cost | Limit change size. Every line has a maintenance cost. |
| P11 | Make the work visible | The agent records its decisions and shows the evidence. |
| P12 | Neutral core, thin adapters | The core never names a harness or a tool. |

## P1. Checks decide

- **Rule:** Work MUST NOT be marked done until the checks for its profile pass. An agent's statement
  that it ran a check is not evidence. The check output is evidence.
- **Reason:** Agents stop when work looks done, and they sometimes claim checks that they did not run.
- **Evidence:** B1, B2, B8, B12, D6, F3.
- **Enforce:** Gate G3 runs the checks in CI, outside the agent session. The agent attaches check
  output to the PR.

## P2. Separate the writer from the judge

- **Rule:** The actor in the implementer role MUST NOT write or change tests, checks, or check
  configuration. This applies to a human and to an agent. A different actor writes the tests from
  the spec and the diff. A different actor reviews. When an agent fills the tester or reviewer
  role, it runs in a fresh session. The pipeline MUST start these roles. A prompt that only asks
  for them is not sufficient.
- **Reason:** Tests from the same actor prove only that the code agrees with that actor's reading
  of the task. This bias applies to people too.
- **Evidence:** B2, B3, B5, B9, B10, B15, E12, F6. Risk: B6.
- **Enforce:** A protected-path check fails the build if an implementer commit changes a test or a
  check path. A commit with no role trailer counts as an implementer commit. Checks are read-only in the agent environment where the harness allows it. Mutation
  score measures the tester.

## P3. Judgment goes into the inputs

- **Rule:** Work MUST NOT start until the input meets the profile's Definition of Ready. The
  Definition of Ready includes acceptance criteria, non-goals, and a test oracle (how to know it
  works).
- **Reason:** Human judgment is most valuable at the start (the ticket) and at the end (the review).
- **Evidence:** D1, D7, D8, D9, D10, D11, H2.
- **Enforce:** Gate G1. An interview ("grill") skill finds the gaps. A template check confirms the
  required ticket fields.

## P4. Context is a budget

- **Rule:** The always-loaded instruction file SHOULD be under 150 lines. It MUST contain only facts
  that the agent cannot find in the repo. Other knowledge MUST load on demand (skills, linked docs).
- **Reason:** Performance decreases as context grows, and generated context files did not help.
- **Evidence:** A1–A9, A12, A15, H6.
- **Enforce:** A size check on the instruction file. A lint for skill size and description format.

## P5. Each component earns its place

- **Rule:** Each generated component MUST have a manifest entry with a purpose, an eval, an owner,
  the models it was tested on, and a review date. At the review date, the owner MUST delete the
  component or record new evidence that it helps.
- **Reason:** What helps one model can hurt the next. Effects are seldom measured, and people feel
  faster when they are not.
- **Evidence:** A3, B4, G1–G9.
- **Enforce:** [lifecycle.md](lifecycle.md). A scheduled CI job opens an issue for each component
  past its review date.

## P6. Enforce what you can state

- **Rule:** If a rule can be stated precisely, it MUST be a check or a hook, not an instruction.
  Prefer, in this order: check, hook, skill, instruction.
- **Reason:** Instructions are advisory. Checks and hooks run every time.
- **Evidence:** B4, B7, B13, B14, C1–C10, F6.
- **Enforce:** Each instruction in the manifest has a field "why not a check". The lifecycle review
  reads it.

## P7. Ceremony scales with risk

- **Rule:** Each profile MUST declare its plan form (plan artifact or decision log) and its gates.
  A repo MAY add gates. A repo MUST record a reason to remove a gate.
- **Reason:** Heavy process on small work wastes review time. Light process on large work is risky.
- **Evidence:** D2–D5, E10, H3.
- **Enforce:** Profile frontmatter. The generator rejects a profile without a plan form and gates.

## P8. Small units, fresh sessions, state in files

- **Rule:** Each session SHOULD do one unit of work. Durable state (plan, progress, decision log,
  task list) MUST be in versioned files in the repo. Hidden harness memory MUST NOT be a source of
  truth.
- **Reason:** Long sessions collect noise. Repo files are visible to all tools and all people.
- **Evidence:** A10, A11, E1–E7, E13.
- **Enforce:** Profiles define session boundaries. Progress and decision-log templates.

## P9. Bounded autonomy

- **Rule:** Each role MUST have the minimum tools and permissions for its job. No role may have
  private data, untrusted input, and an outbound channel at the same time. A human MUST approve each
  destructive action (delete, force push, production data change, deploy).
- **Reason:** Agents have deleted production data.
- **Evidence:** F1–F5.
- **Enforce:** Gate G5. Role permission lists. Sandboxes. Branch protection.

## P10. Volume is a cost

- **Rule:** Each profile MUST set a change-size limit for one PR. A PR over the limit MUST be split
  or get an explicit waiver.
- **Reason:** Large PRs get no-look reviews, and maintenance cost grows with every line.
- **Evidence:** B11, C2, C5, C9, G10, H1.
- **Enforce:** A diff-size check in G3. Complexity caps.

## P11. Make the work visible

- **Rule:** The agent MUST record each decision that it made without a human (decision log). It
  MUST attach the evidence for each acceptance criterion. It MUST state its confidence and the
  open risks.
- **Reason:** A reviewer checks evidence faster than they repeat the work.
- **Evidence:** A10, D3, F7.
- **Enforce:** PR template sections. A check that the sections are not empty.

## P12. Neutral core, thin adapters

- **Rule:** Files in `framework/` outside `adapters/` MUST NOT name a harness, a model, or a spec
  tool. Each harness or tool detail MUST be in an adapter.
- **Reason:** Harnesses and tools change faster than principles.
- **Evidence:** A13, A14, E7, E10, E11, H5.
- **Enforce:** A text check on `framework/` for harness and tool names, with `adapters/` excluded.
