# Vocabulary

Each term has one meaning. Use these terms in all framework files. Adapters map each term to a
harness feature.

| Term | Meaning | Do not use |
| --- | --- | --- |
| harness | The software that runs the model, gives it tools, and controls the loop. | agent tool, IDE |
| model | The language model that the harness calls. | AI, LLM (in rules) |
| session | One run of a harness with one context. A fresh session has no context from another session. | chat, conversation |
| role | A named job for an agent, with its own instructions, tools, and permissions. | persona, sub-agent (in the core) |
| instruction file | The file that the harness loads into every session (repo level or user level). | memory, rules file |
| skill | A folder with a procedure that loads only when a task needs it. | command, prompt |
| hook | A script that the harness runs at a set event (for example before a file edit). | callback |
| check | A program that returns pass or fail with no model judgment. | test (in general), validation |
| eval | A repeatable test that measures how a component changes agent results. | benchmark |
| gate | A point where work stops until an approver (a human or a check) passes it. | approval step |
| stage | One step of the workflow model (for example Plan or Build). | phase |
| profile | The configuration of the workflow model for one type of work. | workflow type, mode |
| artifact | A file that a stage makes (for example a plan, a decision log, a test report). | output, document |
| plan artifact | A file that describes the approach before the build. A human can approve it. | spec (in the core) |
| decision log | A file where the agent records the decisions that it made without a human. | notes |
| Definition of Ready | The fields an input must have before work starts. | DoR |
| component | Any rule, skill, role, hook, check, or CI job that the generator makes. | asset |
| manifest | The file in the target repo that lists each component and its lifecycle data. | registry |
| adapter | The mapping from the neutral core to one harness or one tool. | plugin, driver |
| trigger | The event that starts a profile (a command, a label, a schedule, a CI event). | entry point |
| protected path | A path that a role must not change (for example tests for the implementer). | locked file |
| waiver | A recorded reason to skip a gate or a limit for one item. | exception, override |
