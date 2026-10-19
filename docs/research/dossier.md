# Research dossier: the agent workflow framework

Status: draft v0 (2026-10-17). This dossier is the evidence base for [framework/](../../framework/README.md).

## Purpose

This dossier collects findings about agent-assisted software delivery. Each finding has a source,
the workflow profiles where it applies, and the framework principle that it supports.

## How to read this dossier

- `[S4]` is a citation. The full list is in [Sources](#5-sources).
- Profile tags show where a finding applies:

| Tag | Profile | Tag | Profile |
| --- | --- | --- | --- |
| FP | Full project | CA | Code audit |
| AS | App slice | RM | Refactor or migration |
| ST | Single ticket | DU | Dependency upgrade |
| BT | Bug triage | SP | Spike or prototype |
| DB | Debugging | ALL | All profiles |

- `P1` to `P12` are the principles in [framework/principles.md](../../framework/principles.md).

## 1. Findings by theme

### A. Context and instructions

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| A1 | Model performance decreases as input length increases. This was true for all 18 models tested. | [S14] | ALL | P4 |
| A2 | Context is a finite attention budget. Use the smallest set of high-signal tokens. | [S8] | ALL | P4 |
| A3 | LLM-generated context files decreased task success by about 2% and increased cost by about 23%. Human-written files increased success by about 2.4%. Neither change was statistically significant. | [S5] | ALL | P4, P5 |
| A4 | Human-written context files did better than LLM-generated files by about 7% (significant). Put only facts in the file that the agent cannot get from the README. | [S5] | ALL | P4, P12 |
| A5 | Agents follow instruction files closely. A tool that the file names is used much more often. | [S5] | ALL | P4 |
| A6 | Keep the instruction file to 100–150 instructions, under 300 lines. Instructions go into every prompt, so they are a last resort. | [S2] | ALL | P4, P5 |
| A7 | Make the root `AGENTS.md` a map of about 100 lines, not a manual. Point to deeper docs. | [S12] | ALL | P4 |
| A8 | For each line in `CLAUDE.md`, ask: "Will the agent make mistakes if I remove this line?" If not, remove it. A long file makes the agent ignore rules. | [S10] | ALL | P4, P5 |
| A9 | Use progressive disclosure. Load a concept only when the task needs it (skills, linked files). | [S2] [S26] [S11] | ALL | P4 |
| A10 | Knowledge that is not in the repo does not exist for the agent. Keep plans, specs, and decisions in versioned files. | [S12] | ALL | P8, P11 |
| A11 | Avoid harness "memories". They stay on one machine and hide that a skill must be made or improved. | [S2] | ALL | P8 |
| A12 | Write commands exactly as you type them. Say why a rule exists. List what the agent must never touch. Add a line each time the agent makes a mistake. | [S3] | ALL | P4, P6 |
| A13 | `AGENTS.md` is an open format. More than 60,000 projects use it. It is now part of the Agentic AI Foundation. | [S25] | ALL | P12 |
| A14 | Agent Skills is an open format with three load stages: discovery (name and description), activation (`SKILL.md`), and execution (bundled files). Many harnesses support it. | [S26] | ALL | P12 |
| A15 | Keep `SKILL.md` under 500 lines. Keep references one level deep. A description must say what the skill does and when to use it. | [S11] | ALL | P4 |

### B. Verification and testing

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| B1 | Give the agent a check that it can run: tests, a build, a screenshot. Without a check, "looks done" is the only signal. | [S10] | ALL | P1 |
| B2 | Verification must be outside the generation loop. Run the checks in a container. Mount the checks read-only, so the agent cannot change them. | [S1] | AS ST DB RM DU | P1, P2 |
| B3 | If the AI writes the code and all the tests, the tests prove little. They show only that the code agrees with the AI's own reading of the task. | [S1] | AS ST DB RM | P2 |
| B4 | In 26 prompt conditions with about 160 runs each, no technique name in the prompt made a large difference. TDD prompts gave more tests, but weak tests. | [S4] | ALL | P5, P6 |
| B5 | Agents almost never built two independent implementations for differential tests. They often copied the same bug into both. | [S4] | DB RM | P2 |
| B6 | Runs that used an independent sub-agent audit scored worse. Agents seldom did a fresh-context re-derivation when a skill only asked for it. | [S4] | ALL | P2 (risk) |
| B7 | Structure-aware fuzzing found real bugs in about half of the runs that used it. | [S4] | DB CA | P6 |
| B8 | Agents marked features as done after unit tests or curl checks. End-to-end tests through browser automation improved results. | [S7] | AS ST | P1 |
| B9 | In a long-running harness, the prompt forbids the coding agent to remove or edit tests. The agent changes only a `passes` field. | [S7] | FP AS | P2 |
| B10 | Use a writer and a reviewer in separate sessions. A fresh context reviews better because it is not biased toward its own code. One session can write tests and another can write code. | [S10] | ALL | P2 |
| B11 | A reviewer that you tell to find gaps always finds some. Tell it to report only gaps that affect correctness or the requirements. | [S10] | ALL | P2, P10 |
| B12 | Agents fail in specific ways. They claim tests ran when they did not, and change files outside the scope. They weaken or remove assertions, hide errors, and add fixes nobody asked for. | [S3] [S23] | ALL | P1, P6 |
| B13 | Mutation testing shows weak tests: if a small code change does not fail a test, the test is too weak. | [S1] [S27] | AS ST RM CA | P6 |
| B14 | Choose the test technique by what you can state. Examples: an example (unit), a rule for all inputs (property), or an input format (fuzzing). Also a second implementation (differential), or a relation between inputs (metamorphic). | [S1] | DB RM CA | P6 |
| B15 | Write tests in a different session from the code. | [S1] | AS ST DB RM | P2 |

### C. Structure and deterministic checks

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| C1 | Write rules so that tools can check them, not so that reviewers must judge them. | [S1] [S20] | ALL | P6 |
| C2 | Automate as much of code review as possible. Validations lower the cognitive load of review. | [S1] | ALL | P6, P10 |
| C3 | A fitness function is an automated check on a structural property: dependency direction, layers, no cycles, coupling and size limits. It fails the build. | [S1] [S21] | AS RM CA | P6 |
| C4 | Fitness tools exist for each ecosystem: ArchUnit (Java), dependency-cruiser (JavaScript and TypeScript), import-linter (Python). | [S1] [S27] | AS RM CA | P6 |
| C5 | Complexity caps: cyclomatic complexity, cognitive complexity, nesting depth, parameter count. Power of Ten sets a function length of about 60 lines. | [S1] [S20] | ALL | P6, P10 |
| C6 | The CRAP score combines complexity and test coverage in one gate. | [S1] [S22] | CA RM | P6 |
| C7 | Custom linters and structural tests enforce the architecture. The lint message tells the agent how to fix the error. | [S12] | ALL | P6 |
| C8 | Instructions are advisory. Hooks are deterministic and run every time. | [S10] [S29] | ALL | P6 |
| C9 | Agents copy existing patterns, also bad ones. Recurring background agents scan for drift and open small cleanup PRs. | [S12] | CA RM | P6, P10 |
| C10 | Run the checks on your own machine first. Shift the checks left. | [S1] | ALL | P1 |

### D. Planning and specs

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| D1 | Good tickets give simple prompts. Human judgment goes into the ticket at the start and into verification at the end. | [S2] | ALL | P3 |
| D2 | Iterate on the plan, not on the diff. A plan has: understanding, files to change, approach, acceptance-criteria coverage, out of scope, open questions. | [S3] | FP AS RM | P3, P7 |
| D3 | Several speakers no longer use plan mode. They let the agent pick the recommended options and document them after. | [S2] [S3] | ST BT DU | P7, P11 |
| D4 | Plan mode adds overhead. If you can describe the diff in one sentence, skip the plan. | [S10] | ST BT DU | P7 |
| D5 | Spec-driven tools can over-process small work. One tool made four user stories with 16 acceptance criteria for a small bug. The verbose spec files were hard to review. | [S15] | ST BT DU | P7 |
| D6 | Specs can give a false sense of control. Agents sometimes ignored or over-applied spec instructions. | [S15] | ALL | P1 |
| D7 | Explicit intent helps. Literate programming, RFC 2119 words (MUST, SHOULD, MAY), and ASD-STE100 remove ambiguity. Explicit text has limits, and its effect is tied to the model. | [S1] | ALL | P3, P5 |
| D8 | Use an interview skill ("grill me") to find the gaps in a ticket before work starts. | [S2] [S3] [S24] | FP AS ST | P3 |
| D9 | For large features, let the agent interview you and write a spec. Then start a fresh session to build it. | [S10] | FP AS | P3, P8 |
| D10 | For a long build, an initializer agent expands the request into a structured feature list. Each feature starts as failing. | [S7] | FP AS | P3, P8 |
| D11 | The first tickets you create are the most important. They set the pattern for the rest. | [S2] | FP | P3 |
| D12 | A persona describes one specific type of user, with goals and limits. A team designs for that person, not for an abstract "user". | [S31] | FP AS | P3 |
| D13 | A job story states the situation, the motivation, and the expected outcome: "When ..., I want to ..., so that ...". It gives the context that a user story with a role does not. | [S32] | FP AS ST | P3 |
| D14 | Keep the current specs apart from the proposed changes. Each change holds spec deltas (added, modified, and removed requirements, each with scenarios). When the change is done, the deltas merge into the current specs. The specs then show the system as it is, and the changes show why. | [S34] | FP AS RM | P3, P8 |

### E. Sessions, state, and roles

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| E1 | LLMs are stateless. A clean slate is a feature. What you choose to forget is as important as what you remember. | [S2] | ALL | P8 |
| E2 | Work on one feature per session. Commit, and update a progress file at the end of each session. | [S7] | FP AS | P8 |
| E3 | At session start, read the git log and the progress file, start the app, and run a basic end-to-end check. | [S7] | FP AS DB | P8, P1 |
| E4 | Keep task lists in JSON. Models corrupt JSON less than Markdown. | [S7] | FP AS | P8 |
| E5 | After two failed corrections, clear the context and start again with a better prompt. | [S10] | ALL | P8 |
| E6 | Sub-agents work in clean contexts and return short summaries to a lead agent. | [S8] [S10] | CA FP | P8 |
| E7 | Use small, focused agents. Own your control flow. Make each step a stateless reducer. | [S13] | ALL | P8, P12 |
| E8 | Role agents in one demo: planner, coder, tester, reviewer, test planner, test generator, test healer. | [S3] | AS ST | P2 |
| E9 | Role-based frameworks (for example BMAD) use analyst, product manager, architect, scrum master, developer, and QA agents. | [S30] | FP AS | P2 |
| E10 | Start with the simplest solution. Use a fixed workflow for well-defined tasks. Use an agent only when the steps cannot be known in advance. | [S6] | ALL | P7, P12 |
| E11 | Workflow patterns: prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer. | [S6] | ALL | P12 |
| E12 | Break work into different sessions when the agent must check its own work. | [S3] | ALL | P2, P8 |
| E13 | Start to run 2 or 3 agents at the same time. | [S2] | AS ST DU | P8 |
| E14 | A persona in the system prompt did not improve model results on objective questions. The effect of each persona was mostly random, and an automatic choice of the best persona was no better than a random choice. | [S33] | ALL | P5, P7 |

### F. Autonomy and safety

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| F1 | An agent deleted a production database during a code freeze. | [S3] [S19] | ALL | P9 |
| F2 | "Autonomy without boundaries is not a workflow. It is a risk." | [S3] | ALL | P9 |
| F3 | Three gates come before a human spends attention: in the editor, on the PR, and the human gate. | [S3] | ALL | P1, P9 |
| F4 | Lethal trifecta: private data, untrusted content, and a way to send data out. Do not give all three to one agent. | [S18] | ALL | P9 |
| F5 | Use permission allowlists and OS-level sandboxing. Auto mode uses a classifier to block risky actions. | [S10] | ALL | P9 |
| F6 | When the AI touches a check, flag it. | [S1] | ALL | P2, P6 |
| F7 | Ask "How certain are you?" before you approve. Ask again before you merge. | [S3] | ALL | P11 |
| F8 | Event text (an issue title or body, a PR title, a label) in an inline CI expression can inject shell commands. Pass it to the step through an environment variable. | [S35] [S36] | ALL | P9 |
| F9 | A CI job output that contains a secret is redacted, and the next job does not get it. | [S36] | ALL | P9 |
| F10 | An agent that reads untrusted issue text in CI needs a short-lived token with minimum permissions and a tool allowlist. A secret scrub reduces prompt-injection risk, but does not remove it. | [S37] | ALL | P9 |
| F11 | A CI job that runs from the base branch of a pull request is not changed by the pull request. It is safe only if it does not check out or run code from the pull request. | [S38] | SP | P6, P9 |
| F12 | A file tool of the agent harness reads with no prompt only in the working folder and the added folders. An allow rule for the tool with no path allows all paths. Then a CI role can read the process environment. It can put the harness secret in its report. An allow rule with a path limits the tool. | [S39] | ALL | P9 |
| F13 | A CI job with no time limit runs for up to 360 minutes on a hosted runner. A headless agent run has no turn limit by default. A turn limit stops the run with an error. | [S40] [S41] | ALL | P9 |
| F14 | A mention of a person or a team in a comment notifies them. A zero-width space after the `@` stops the mention link. In a quote block, a raw end tag closes the quote, so the text after it is outside the quote. A zero-width space after each `</` keeps all lines in the quote. | [S42] | ALL | P9 |

### G. Measurement and component lifecycle

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| G1 | Delete skills, prompts, and context every 6 months. | [S1] | ALL | P5 |
| G2 | The effect of explicit instructions is seldom measured. | [S1] | ALL | P5 |
| G3 | Tutorial-style testing skills were ignored or made results worse. One skill increased cost by 26–41%. Write instructions that change default behavior, not tutorials. | [S4] | ALL | P5 |
| G4 | Build evaluations first: find gaps without the skill, write three scenarios, measure a baseline, then write the minimum instructions. | [S11] | ALL | P5 |
| G5 | Test each skill with each model that you use. A skill that suits one model can need changes for another. | [S11] | ALL | P5 |
| G6 | Start agent evals with 20–50 tasks from real failures. Use code-based graders first. Read the transcripts. | [S9] | ALL | P5 |
| G7 | Capability evals start with a low pass rate. Regression evals stay near 100%. Use pass^k (all k trials pass) when consistency matters. | [S9] | ALL | P5 |
| G8 | Developers were 19% slower with AI, but they believed they were 20% faster. | [S16] | ALL | P5 |
| G9 | The 2026 follow-up says developers are probably faster now, but the data is "only very weak evidence" of the size. | [S17] | ALL | P5 |
| G10 | Maintenance scales with volume. 10 times the code costs at least 10 times as much to maintain. | [S1] | ALL | P10 |

### H. Human role and throughput

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| H1 | The slop loop: more vibe coding gives bigger PRs, then no-look reviews, then unknown code ships. The loop feeds itself. | [S1] | ALL | P10 |
| H2 | Humans steer: they set priorities, turn feedback into acceptance criteria, and validate outcomes. When an agent fails, find the missing tool, guardrail, or document. | [S12] | ALL | P3, P5 |
| H3 | At high agent throughput, one team used minimal merge gates and re-ran flaky tests. The authors say this is risky at lower throughput. | [S12] | DU ST | P7 |
| H4 | Software factories: a ticket that moves from Backlog to Ready starts an agent. | [S2] | ST DU BT | P3 |
| H5 | The harness controls the model. The harness from the model's maker is often the best. | [S2] | ALL | P12 |
| H6 | Disable tools that you do not need. Skills are not free. | [S2] | ALL | P4, P5 |

### I. Modes (who drives the work)

| ID | Finding | Source | Applies to | Supports |
| --- | --- | --- | --- | --- |
| I1 | Run AI in many places: chat, local, container, server, a GitHub issue, Slack. Most teams need several. | [S2] | ALL | modes |
| I2 | Software factories: humans focus on the inputs, and agents do the rest. | [S2] [S12] | ST DU BT | agent-centric |
| I3 | Work alone, or pair? Heavy processes are less necessary. | [S2] | ALL | modes |
| I4 | Treat the AI as a pair programmer. The human enforces TDD, catches design drift, and rejects shortcuts. | [S23] | AS RM SP | human-centric, pair |
| I5 | One team wrote no code by hand for five months. Humans set priorities and validated outcomes. | [S12] | ALL | agent-centric |
| I6 | Developers felt faster with AI but were slower in a controlled study. Measure each mode; do not assume. | [S16] [S17] | ALL | P5, mode metrics |
| I7 | Ticket in, draft PR out, with three gates before human attention. | [S3] | ST AS | agent-centric, hybrid |
| I8 | Workflows suit well-defined tasks. Agents suit open-ended tasks. Start with the simplest option. | [S6] | ALL | preset choice |

## 2. Conflicts and resolutions

| # | Conflict | Resolution in the framework |
| --- | --- | --- |
| 1 | Iterate on a plan artifact [S3] **against** skip plan mode and log decisions after [S2] [S10]. | The profile decides. Large scope (FP, AS, RM) uses a plan artifact and gate G2. Small scope uses a decision log. See [gates.md](../../framework/gates.md). |
| 2 | The implementer writes tests [S2] **against** tests from the same session only agree with the code [S1] [S4]. | Tests ship in the same workflow and PR. A separate tester role writes them in a fresh session. The implementer cannot change test files. A check enforces this. See P2. |
| 3 | Separate sessions improve review [S10] **against** independent sub-agent audits scored worse [S4]. | Risk: separation alone is not enough. The pipeline, not a prompt, must start the tester. Measure the tester with mutation score and acceptance tests. Eval the tester role. |
| 4 | Agent makers recommend generated context files **against** generated files decreased success [S5]. | The generator renders human-written templates and repo facts only. It does not write free LLM prose into the instruction file. |
| 5 | Avoid memories [S2] **against** write structured notes [S8] [S7]. | Notes are allowed only as versioned repo files (plan, progress, decision log). Hidden harness memory is not a source of truth. |
| 6 | Minimal merge gates [S12] **against** three gates before human attention [S3]. | The profile and the repo risk decide. Gate G3 (checks) is always on. The human PR gate is optional only for profiles with low risk and only when the repo config allows it. |
| 7 | Developers feel faster [S16] **against** measured slowdown [S16] [S17]. | Measure outcomes. The framework tracks lead time, rework, escaped defects, review time, and cost for each merged PR. |
| 8 | Write no code by hand [S2] [S12] **against** the human as an active pair [S23]. | Both are valid. They are presets. The [mode](../../framework/modes.md) selects the driver of each stage. The gates do not change with the mode. |
| 9 | Controlled language such as ASD-STE100 removes ambiguity [S1] **against** explicit text has limited, model-tied effects [S1] [S4]. | STE applies to human-facing text, where the reader is a person. Agent-facing text uses STE only where an eval shows a gain. Review time, rework, and a quarterly blind A/B decide if STE stays. See [writing.md](../../framework/writing.md). |
| 10 | Role-based frameworks give agents personas such as analyst or product manager [S30] **against** a persona in a prompt does not improve results [S33]. | Personas describe the users of the product, not the agents. Roles stay plain jobs with instructions, tools, and permissions. See [workflow-model.md](../../framework/workflow-model.md#personas). |

## 3. Gap analysis of this repo (brawblan/ai-workflow, v0.2.1)

| Current item | Maps to framework stage | Gap |
| --- | --- | --- |
| `project-setup` skill and constitution templates | Shape (FP) | Good base. Must become an output of the generator, not a separate path. |
| `sdd-plan`, `sdd-build` | Plan, Build | OpenSpec-specific. Move to the spec-tool adapter. Core needs a plain plan format. |
| `ticket-delivery` | Verify, Deliver | Verifies against acceptance criteria in the same session that built the code. Conflicts with P2. |
| `dev-pr` | Deliver | Fits. No gate or role metadata. |
| `backlog-sequencer` | Intake | Fits the Intake stage. |
| `ste-writing` | Cross-cutting | Fits. Candidate for an eval (does it shorten text?). |
| `docs/tips/README.md` habit 4 ("Approve the plan before the code") | Plan | Conflicts with resolution 1. Update after approval. |
| (none) | Shape | No interview ("grill") skill. |
| (none) | Test, Review | No tester role. No reviewer role. No protected-path check. |
| (none) | BT, DB, CA, RM, DU, SP | No profiles for these workflow types. |
| (none) | Learn | No component manifest, no evals, no review dates. |

## 4. Parking lot (ideas for later)

- Differential testing with `git bisect run` to find the commit that caused a regression [S1].
- Recurring "garbage collection" agents that open small cleanup PRs [S12].
- Per-role model choice: a stronger model plans, a cheaper model builds [S2].
- An LLM judge that compares the diff with the plan (scope drift score) [S3].
- Open models that run locally for low-risk roles [S2].
- A cost budget for each profile run.

## 5. Sources

Internal sources are the talk notes in the claude.ai project "Automation and Workflows". They are not
in this repo.

| ID | Source |
| --- | --- |
| S1 | Stephen Shary, "Exotic Agentic Development Strategies: Everything old is new again", talk, 2026-10-15. Talk notes. |
| S2 | Cory House, "Choosing an AI Coding Workflow", talk, 2026-10-15. Talk notes. |
| S3 | Avindra Fernando, "Building the AI-first Developer Stack", talk, 2026-10-15. Talk notes. |
| S4 | Dan Luu, [agentic testing](https://danluu.com/agentic-testing/). |
| S5 | Gloaguen, Mündler, Müller, Raychev, Vechev, [Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?](https://arxiv.org/pdf/2602.11988), arXiv 2602.11988, 2026. |
| S6 | Anthropic, [Building effective agents](https://www.anthropic.com/research/building-effective-agents), 2024-12-19. |
| S7 | Anthropic, [Effective harnesses for long-running agents](https://anthropic.com/engineering/effective-harnesses-for-long-running-agents), 2025-11-26. |
| S8 | Anthropic, [Effective context engineering for AI agents](https://anthropic.com/engineering/effective-context-engineering-for-ai-agents), 2025-09-29. |
| S9 | Anthropic, [Demystifying evals for AI agents](https://anthropic.com/engineering/demystifying-evals-for-ai-agents), 2026-01-09. |
| S10 | Anthropic, [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices). |
| S11 | Anthropic, [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices). |
| S12 | Ryan Lopopolo (OpenAI), [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/), 2026-02-11. |
| S13 | HumanLayer, [12-Factor Agents](https://github.com/humanlayer/12-factor-agents). |
| S14 | Hong, Troynikov, Huber (Chroma), Context Rot, 2025-07-14. Code: [chroma-core/context-rot](https://github.com/chroma-core/context-rot). |
| S15 | Birgitta Böckeler, [Understanding Spec-Driven-Development: Kiro, spec-kit, and Tessl](https://www.martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html), 2025-10-15. |
| S16 | METR, [Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/), 2025-07-10. |
| S17 | METR, [uplift update](https://metr.org/blog/2026-02-24-uplift-update/), 2026-02-24. |
| S18 | Simon Willison, [The lethal trifecta for AI agents](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/), 2025-06-16. |
| S19 | eWeek, [AI agent wipes production database](https://www.eweek.com/news/replit-ai-coding-assistant-failure/), 2025. |
| S20 | Gerard Holzmann, The Power of Ten: Rules for Developing Safety-Critical Code, IEEE Computer, 2006. [Summary](https://en.wikipedia.org/wiki/The_Power_of_10:_Rules_for_Developing_Safety-Critical_Code). |
| S21 | Ford, Parsons, Kua, [Building Evolutionary Architectures](https://www.thoughtworks.com/insights/books/building-evolutionaryarchitectures-second-edition), 2nd edition. |
| S22 | Google Testing Blog, [This Code is CRAP](https://testing.googleblog.com/2011/02/this-code-is-crap.html), 2011. |
| S23 | Kent Beck, [Augmented Coding: Beyond the Vibes](https://tidyfirst.substack.com/p/augmented-coding-beyond-the-vibes). |
| S24 | Matt Pocock, [grilling skill](https://skills.sh/mattpocock/skills/grilling). |
| S25 | OpenAI, [Agentic AI Foundation](https://openai.com/index/agentic-ai-foundation/), 2025-12-09. |
| S26 | [Agent Skills](https://agentskills.io/home) open format. |
| S27 | Tool docs: [import-linter](https://import-linter.readthedocs.io/en/stable/readme.html), [dependency-cruiser](https://github.com/sverweij/dependency-cruiser), [Stryker incremental mode](https://stryker-mutator.io/docs/stryker-js/incremental/). |
| S28 | Anthropic, [claude-code-action](https://github.com/anthropics/claude-code-action) (GitHub Actions). |
| S29 | Anthropic, [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide). |
| S30 | [The BMAD Method explained](https://codemyspec.com/blog/bmad-method-explained). |
| S31 | Alan Cooper, The Inmates Are Running the Asylum, Sams, 1999. |
| S32 | Alan Klement, "Replacing the User Story with the Job Story", JTBD.info, 2013. |
| S33 | Zheng, Pei, Logeswaran, Lee, Jurgens, [When "A Helpful Assistant" Is Not Really Helpful: Personas in System Prompts Do Not Improve Performances of Large Language Models](https://arxiv.org/abs/2311.10054), arXiv 2311.10054, Findings of EMNLP 2024. |
| S34 | Fission AI, [OpenSpec](https://github.com/Fission-AI/OpenSpec), MIT license. The idea of spec deltas that merge into current specs. Cornerstone uses the idea, not the tool (D18, D21). |
| S35 | GitHub Security Lab, [Keeping your GitHub Actions and workflows secure Part 2: Untrusted input](https://securitylab.github.com/resources/github-actions-untrusted-input/). |
| S36 | GitHub Docs, [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use), and the workflow syntax for job outputs. Read 2026-10-18. |
| S37 | Anthropic, [claude-code-action security](https://github.com/anthropics/claude-code-action/blob/main/docs/security.md), v1.0.252. Read 2026-10-18. |
| S38 | GitHub Security Lab, [Keeping your GitHub Actions and workflows secure: Preventing pwn requests](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/), 2021. The `pull_request_target` event. |
| S39 | Anthropic, [Claude Code: Configure permissions](https://code.claude.com/docs/en/permissions) and [Security](https://code.claude.com/docs/en/security). Read 2026-10-18. A local test with Claude Code 2.1.302 on 2026-10-18 confirmed it. `--allowedTools Read,Grep,Glob` read a file outside the working folder and `/proc`. `Read(./**)` with the event folder blocked them. |
| S40 | GitHub Docs, [Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) (`jobs.<job_id>.timeout-minutes`, default 360) and [Actions limits](https://docs.github.com/en/actions/reference/limits) (6 hours for each job on a hosted runner). Read 2026-10-18. |
| S41 | Anthropic, [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference) (`--max-turns`: no limit by default, exits with an error at the limit) and [claude-code-action usage](https://github.com/anthropics/claude-code-action/blob/main/docs/usage.md) (`--max-turns` in `claude_args`). Read 2026-10-18. |
| S42 | GitHub Docs, [Basic writing and formatting syntax](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax) (a mention notifies the person or team). Read 2026-10-18. A test with the GitHub Markdown API (`POST /markdown`, `gfm` mode) on 2026-10-18 confirmed the rest. Without the frame, `@user` gave a mention link, and the text after a `</blockquote>` line was outside the quote. With the frame, no mention link was in the output, and all lines stayed in the quote. |
