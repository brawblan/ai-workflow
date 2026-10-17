# Writing with Simplified Technical English

Agents write long, vague text by default. A small set of rules from ASD-STE100 (Simplified
Technical English) fixes most of it.

## The rules I give every agent

These are in [`global/AGENTS.md`](../../global/AGENTS.md):

- Give the answer or the result first. Then give the details.
- Procedures: 20 words or fewer per sentence. Descriptions: 25 words or fewer.
- Write one instruction per sentence, in the imperative. Put the condition first.
- Use the active voice and simple tenses. Keep the articles (a, an, the).
- Each word has one meaning.
- Do not use idioms or vague words (simply, just, easily, various, robust, leverage). <!-- ste-ignore -->
- Use lists and tables more than paragraphs.

The full rule set is in
[`ste-writing/references/ste.md`](../../plugins/workflow/skills/ste-writing/references/ste.md).

## Before and after

| Before | After |
| --- | --- |
| "It might be a good idea to consider running the tests before you go ahead and push." | "Run the tests. Then push." |
| "The config file is being read by the loader." | "The loader reads the config file." |
| "We leverage a robust caching layer." | "A cache stores the results for 10 minutes." |

## Add a project dictionary

Give each important term one meaning. Put a table in the repo, for example `docs/style/ste.md`:

| Term | Meaning | Do not use |
| --- | --- | --- |
| tenant | One customer organization on the platform. | org, customer, account |
| remove | Take out an item. The item can come back. | delete |
| delete | Destroy stored data. The data cannot come back. | remove, erase | <!-- ste-ignore -->

The `ste-writing` skill reads this file when it exists.

## Do not rewrite old docs

Apply the rules to new text, and to text that you edit for another reason. A full rewrite only for
style makes a large diff with no change in meaning.
