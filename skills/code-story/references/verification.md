# Verification pass

One pass, before the user sees the story. A fresh reviewer, with no stake in the prose, reads the built story against the code. Run it once; it is not a loop.

## Brief for the reviewer

Give the reviewer this brief, with the paths filled in. Read-only: the reviewer changes nothing.

> You are checking a code story: an HTML walkthrough of a change, written by another agent. The story's source is `DIR/story.md`, and `DIR/story.txt` is the built page as plain text (what the reader sees, with line numbers); the change's index is `DIR/index.json` (repo path, base, merge-base and head commits, every hunk). The repo is at `REPO`. Code in the story is rendered from git, and a build check already guarantees every change is shown, so don't check coverage or code text.
>
> Check the prose:
> 1. **Claims.** Every statement about what the code does, compared with the code beside it and the code it depends on (`git show HEAD_SHA:path`). Flag anything wrong, overstated or unsupported.
> 2. **Gaps.** Important flows, side effects, failure paths or risks the change introduces that the story misses or misrepresents.
> 3. **Mismatches.** Places where the PR description (in `index.json`), docs, tests and code disagree, and the story doesn't say so or picks the wrong side.
> 4. **Padding.** Sentences, notes or chapters a reviewer wouldn't miss.
> 5. **Prose rules.** If the authoring agent loaded prose rules (named here: RULES), the prose against them.
>
> Report a numbered list: the chapter and quote, what's wrong, the evidence (`path:line` at a commit), and the fix. Nothing else.

For a tour, give the same brief with these changes: it checks "a code tour: an HTML walkthrough of how an app works", `index.json` holds the repo path and the pinned commit, and there's no change or coverage. Replace items 2 and 3 with:

> 2. **Gaps.** What a newcomer needs to understand the app and its main flow that the tour misses or gets wrong: an entry point, a step of the flow, where state or configuration lives.
> 3. **Mismatches.** Places where the README or docs and the code disagree, and the tour doesn't say so or picks the wrong side.

Where the harness has subagents, run the reviewer as one. Otherwise do the pass yourself as a separate read, with the brief in front of you, after the build succeeds.

## Acting on the report

The reviewer can be wrong. Check each item against the code before changing anything; you stay responsible for the story. Fix what holds up, rebuild, and move on to hand-over.
