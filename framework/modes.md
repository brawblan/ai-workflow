# Modes

A mode says who does the work in each stage: an agent, a human, or a human with an agent in the same
session. The mode does not change the gates (see [gates.md](gates.md)). The profile sets the gates.

## Actors and drivers

- An **actor** is a human or an agent that fills a [role](workflow-model.md#roles).
- The **driver** of a stage is the actor that does the work in that stage.

| Driver value | Meaning |
| --- | --- |
| `agent` | An agent does the work in its own session. A human answers questions only. |
| `human` | A human does the work. No agent changes files in this stage. |
| `pair` | A human does the work with an agent in the same session. The human decides each change. |
| `checks` | Programs do the work. No actor. Used only for Verify. |

Roles are actor-neutral. A human or an agent can fill any role.

## Separation rule for all actors

The separation rule (P2) applies to each actor, human or agent:

1. The actor that fills the implementer role MUST NOT fill the tester or reviewer role for the same
   item.
2. A `pair` session counts as one actor. The human and the agent in it are both the implementer.
3. If a human implements, an agent tester or a different human writes the tests.
4. If an agent implements, an agent in a fresh session or a human writes the tests.

## Presets

Each profile has a default preset. A repo or a ticket can select a different preset or change single
stage drivers (see [customization.md](customization.md)).

| Stage | agent-centric | hybrid | human-centric |
| --- | --- | --- | --- |
| Intake | agent | agent | human |
| Shape | agent (interviews the human) | agent (interviews the human) | human |
| Plan | agent | human, or `pair` | human, or `pair` |
| Build | agent | agent | human, or `pair` |
| Test | agent | agent | agent |
| Verify | checks | checks | checks |
| Review | agent, then human at G4 | agent, then human at G4 | agent, then human at G4 |
| Deliver | agent (after G4) | human | human |
| Learn | human | human | human |

Caption: the agent always writes the tests in human-centric mode, because the human is the
implementer (separation rule 3). Verify and Learn are the same in all modes.

### When to use each preset

| Preset | Use when | Typical trigger | Runs where |
| --- | --- | --- | --- |
| agent-centric | The input is complete and the work is routine. Ticket in, draft PR out. | A label, a schedule, a CI event | CI or a cloud session |
| hybrid | A human must own the design, but an agent can do the build. | A command after G2 | CI or a local session |
| human-centric | The work needs human judgment in the build: new design, unclear domain, or learning. | A person starts it | A local session |

## Rules

1. The mode MUST NOT remove or add a gate. G3 and G5 stay on in each mode.
2. The decision log is required for each stage that an agent drives. A human driver MAY skip it.
3. An agent-driven stage MUST write its state to files before its session ends (P8). A human-driven
   stage SHOULD do the same when the work stops for more than one day.
4. Each item records its mode and its stage drivers. The lifecycle metrics compare the modes (see
   [lifecycle.md](lifecycle.md#metrics-for-each-profile)).
5. A stage driver can change during an item, for example from `agent` to `pair` after 3 failed loops.
   The change is recorded in the decision log.

## Solo developer

A solo developer is often the only human. In human-centric mode, that human implements and also
approves G4. This is the only exception to gate rule 3. All of these conditions MUST be true:

1. The repo config states `owners.solo: true`.
2. An agent reviewer in a fresh session reported on the PR.
3. All checks (G3) passed.
4. The PR records that the solo exception applied.
