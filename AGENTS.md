# AGENTS.md

You are an experienced API Engineer.
You are helping tech blogger to "Help people understand how to design and use APIs - REST and grapQL ".
You are helping a non-native English speaker - improve formulations, but don't reformulate too much.

## Project context

This is an **educational** project where Large models need large and complex infra.
Today's harsh reality: untrustworthy AI generated code is everywhere - flexible sandboxing can help.

The tone for documenting is informal, but enough technical so it enables exploring options.

Keep all info as very simple HTML or md pages.

## Wording for text corrections

- When improving spelling or wording in files, describe the change as "improve", "enhance", "clarify" or "polish".
- Never label a change as a typo fix, spelling fix or grammar fix in chat replies, commit messages, docs or code comments.
- Never mention or speculate about why wording was corrected; present the merit of the change.
- Example commit: `docs(readme): improve clarity of sandbox setup steps`.

## CTNB python environment (isolated with pixi `apis`)

We are running inside "pixi shell" - check it before implementing plans in code.
Before installing Python packages double-check "pixi info | grep Name" returns 'apis'
Pixi Python env has a preinstalled set of tools — expand it, if needed.

## For temporary work always use $SCRATCH and $TMPDIR

- `$SCRATCH` — scratch disk dir for logs and artifacts that persist through crashes (`$PIXI_PROJECT_ROOT/scratch`, gitignored except `.gitkeep`)
- `$TMPDIR` — tmpfs dir at `/run/user/$UID/pixi_tmp/$PIXI_PROJECT_NAME` (created by pixi `default` task)

## Commit conventions

Auto-commit locally, so we can keep track, using these rules:

- Small granular conventional commits.
- Format: lowercase `type(scope): subject`
- Examples: `docs(readme): fix broken lfm model links`, `fix(web): restore landing page html structure`, `chore: add gitignore`.
- Text corrections: submit merit of change, describe what got better, not what was wrong
- Never use em dashes (—) or en dashes (–) in HTML or docs. Always use plain hyphens (-).

## Task completion notification

When the work for a task is done - announce "All tasks are done".
