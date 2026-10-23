# Personas

<!-- Guide: This file owns the people who use the product. A persona is a user, not an agent role.
Write 1 to 5 personas. Each ticket names its personas in a "Personas: <IDs>" line, and each plan maps
its acceptance criteria to job story IDs. `stone check` (K18) tests this format. Keep each field
name as it is. Remove each Guide comment when you fill the file. -->

## <Persona name>

<!-- Guide: id is a slug (lowercase letters, digits, and hyphens), for example "analyst". Each job
story ID starts with the persona id. Write 3 to 5 job stories. Each job story has the form
"When I <situation>, I want to <motivation>, so that <outcome>." -->

- id: <slug>
- who: <one line: role, context, and how often they use the product>
- jobs:
  - <slug>.J1: When I <situation>, I want to <motivation>, so that <outcome>.
  - <slug>.J2: When I <situation>, I want to <motivation>, so that <outcome>.
  - <slug>.J3: When I <situation>, I want to <motivation>, so that <outcome>.
- limits:
  - device: <for example: phone only, slow network>
  - skill: <for example: no technical knowledge>
  - access: <for example: read-only, no admin rights>
- evidence: assumed

<!-- Guide: "assumed" means that nobody tested the persona with real users. A review flags each
assumed persona. When research confirms it, write "validated" and the source, for example
"validated (6 interviews, 2026-09)". -->
