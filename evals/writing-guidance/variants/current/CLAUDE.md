## Writing

Write replies with the core rules of ASD-STE100 (Simplified Technical English):

- Give the answer or the result first. Then give the details.
- Procedures: 20 words or fewer per sentence. Descriptions: 25 words or fewer.
- Write one instruction per sentence, in the imperative. Put the condition first ("If X, do Y").
- Use the active voice and simple tenses. Keep the articles (a, an, the).
- Each word has one meaning. If the project has an STE dictionary, use its approved terms.
- Do not use idioms or vague words (simply, just, easily, various, robust, leverage).
- Use lists and tables more than paragraphs.

## Visuals

- If a reader understands a point faster by seeing it, use a visual.
- Diagrams: add them only on request. Use Mermaid in repo files, and a small ASCII sketch in terminal chat.
- Web pages and explainers: offer them in one line first. The default explainer is an animated
  step-through page with optional browser narration. Make an MP4 only on request.
- Use only free tools that are already installed. Do not suggest paid tools or subscriptions.

# ste-writing

Write text that a reader understands on the first read.

1. **Load the rules.** Read the rules below.
2. **Load the project terms.** If the repo has its own dictionary (for example
   `docs/style/ste.md`), read it. Its terms come first.
3. **Check for visuals.** If the text explains a flow, a lifecycle, or a comparison of 3 or more
   options, read `references/visuals.md`. Add the diagram it describes.
4. **Write.** Give the main point first. Keep procedure sentences to 20 words or fewer.
5. **Review.** Before you hand over the text, check it against each rule in `ste.md`. Fix:
   - Sentences over the word limit
   - Passive voice in procedures
   - Vague words and idioms
   - Terms that the dictionary replaces

Do not rewrite an existing doc only to apply these rules. Apply them to new text, and to text that
you edit for another reason.

# Writing style: Simplified Technical English

These are the core writing rules of ASD-STE100 (Simplified Technical English, STE), plus a
dictionary. The goal is text that a reader understands on the first read.

Use these rules for:

- Specs, proposals, designs, and task lists
- New docs, and docs that you edit for another reason
- GitHub issues, PR bodies, and commit messages
- Agent chat replies

Do not rewrite an existing doc only to apply these rules.

## Rules

### Words

1. If a term is in the dictionary, use the approved term. Each word has one meaning.
2. Use simple tenses: present, past, and future. Do not use "-ing" forms as verbs.
   Write "The sync runs", not "The sync is running".
3. Use a one-word verb if one exists. Write "find", not "find out".
4. Do not use idioms, slang, or figures of speech.
5. Do not use vague words: simply, just, easily, various, appropriate, robust, leverage, utilize, etc.
6. Keep the articles (a, an, the). Do not write in telegraph style.
7. Code names, product names, and file paths are allowed. Put code names in backticks.

### Sentences

8. Procedures: 20 words or fewer per sentence. Descriptions: 25 words or fewer.
9. Write one instruction per sentence. Use the imperative: "Run the tests."
10. Put the condition first: "If the build fails, read the log."
11. Use the active voice in procedures. In descriptions, use it when you can.
12. Use a list for 3 or more items. Number the steps of a procedure.

### Paragraphs

13. Put one topic in each paragraph. Use 6 sentences or fewer.
14. Give the main point first. Then give the details.
15. In a warning, give the instruction first. Then give the reason.

### Chat replies

- Give the answer or the result first.
- Use lists and tables more than paragraphs.
- Say what you did, what you found, and what you need from the reader.

## Dictionary

Use the term in the left column. Do not use the terms in the right column for the same meaning.
Add a term when a word causes confusion. Keep one meaning for each word.
Code names, table names, and test-layer names are technical names. The "Do not use" column does
not apply to them.

### Project dictionary

Each project keeps its own dictionary of domain terms, for example in `docs/style/ste.md`.
If the project has one, its terms come first. Use this table shape:

| Term | Meaning | Do not use |
| --- | --- | --- |
| tenant | One customer organization on the platform. | org, customer, account |

### Removal (all projects)

| Term | Meaning | Do not use |
| --- | --- | --- |
| remove | Take out a member, file, setting, or code. The item can come back. | delete (for these items) |
| delete | Destroy stored data. The data cannot come back. | remove, erase |
| purge | Delete data because a retention rule requires it. | clean up |
| drop | The SQL operation `DROP` only. | delete (for tables) |
