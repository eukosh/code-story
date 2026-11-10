# Telling the story

Guidance, not a recipe. Every change has its own shape; use what fits and leave the rest.

## The spine

Follow the program, not the file list. Find the first moment the changed behaviour is hit at runtime (a request arriving, a job starting, a value being read) and walk forward from there, one chapter per stop. Each chapter answers "what happens next, and what changed about it".

- Keep startup, per-request and deploy-time concerns in separate chapters, each with a `where=` that says when it runs ("Once per instance, from main.py", "Every request, AccessCheck"). A reader should always know which of these they are in.
- Show config where it is read, and infrastructure where it is consumed: the env var beside the setting that reads it, the Terraform beside the code that needs the secret.
- When one value is the thread through the whole change (a user id, a key, a schema version), make it a trace.
- For data pipelines and models (SQL, dbt, ETL jobs), the flow is the data's: follow a row from where it lands to where it's read, one chapter per transformation that changed, even when that's not the order of the code in the file. `where=` names the run and the step ("Every dbt run, base_contacts").

## Context

The reader is new to this code. Give them what they need one hop out from each change: who calls it, what consumes its result, where a value comes from, what shape the data has. A test fixture is often the clearest statement of a data shape anywhere in the repo. Keep each frame to the lines its point is about: on the page the reader can unfold the rest of the file from any frame, and click a name to open its definition when the page has the file that defines it. Mark mechanisms that live outside the repo (another service, a module in another repo) with an `external` note instead of guessing at them. When a dependency has a local checkout, read it at the version the repo pins (`git show v2:path`), not at whatever the checkout has open, and name that version in the note.

## Evidence beside claims

Code dominates, prose stays lean. A consequential claim sits right next to the code that backs it, so the reader can check it without scrolling. Use a step with cards when a specific line needs support from elsewhere (where a setting comes from, which test pins a rule); put general background in the chapter flow.

## Failure paths

Put each failure path at its decision point, as a fork: a request without a token, a user with no access, a store that's unavailable. Include unchanged exits when they're part of the same decision; say so in the branch.

## Things that are easy to miss

- **Ripples**: the same mechanical edit at many sites renders as one frame plus "N more sites". Explain it once.
- **Deliberate leftovers**: code or infrastructure the change keeps on purpose (kept for a phased rollout, a shared stack) deserves a sentence saying why, or reviewers will flag it.
- **Symlinks**: when one file is symlinked into several places, one diff changes all of them. Say which.
- **Mismatches**: when the PR description, docs, tests and code disagree, show the evidence and say which one is right, in a `mismatch` note.
- **Cutover risks**: data that must exist first, readers downstream that will see a new shape. A `question` note, near the code that causes it.

## Claims you can't check

Numbers and behaviour that live outside the repo (prod counts from the PR, what another service does with a flag) are the PR's or the docs' claims, not yours. Attribute them ("The PR reports…") or leave them out.

## Prose

- Every line under a heading carries information. A subtitle that restates the heading goes; fold its content into the title, the paragraph or a note.
- One idea per paragraph, short. Name things by what they do in this codebase.
- Chapter titles state what happens ("Identity comes from `claims.user_id`"), not a topic ("Identity").
- Notes are for things a reviewer should act on or would otherwise miss. A story full of callouts reads as noise.
- Appendices hold what belongs to the change but not to the walk: docs, packaging, version bumps.
