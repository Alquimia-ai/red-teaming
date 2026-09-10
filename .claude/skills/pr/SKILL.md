---
name: pr
description: Open a GitHub pull request against develop with a description built from every commit in the branch. Use when a phase or feature branch is ready for review.
allowed-tools: Bash, Grep, Read, Glob
---

# Create Pull Request

Open a pull request with the `gh` CLI, describing **every** commit in the branch.

## When to use this skill

- The current branch has commits that are ready for review.

Do **not** use this skill to:

- commit changes — use `/commit` first;
- promote `develop` into `main` unless the user says "release" or "promote" (that PR targets `main`).

## Steps

1. **Detect the base branch.** The default base is `develop`. Use `main` only when the user asks for
   a release/promotion or the current branch is `develop` itself. Store it as `BASE`.
2. **Gather context** (run in parallel):
   - `git status` (never `-uall`) — warn and stop if there are uncommitted changes;
   - `git log $BASE..HEAD` (full messages, not `--oneline`);
   - `git diff $BASE...HEAD --stat`;
   - `git diff $BASE...HEAD` when the stat alone does not explain a change.
3. **Push** the branch if it has no upstream or is behind: `git push -u origin HEAD`.
4. **Write the description** into a temporary file (see format) from *all* commits and the diff.
5. **Create the PR:**

   ```bash
   gh pr create --base "$BASE" --title "<title>" --body-file /path/to/body.md
   ```

6. Return the PR URL.

## PR title

- Derived from the intent of the whole branch, not one commit.
- Lowercase, imperative, at most 70 characters (e.g. `add the runner and dispatch backends`).

## PR description format

```markdown
## Summary

<1–3 sentences: what this PR accomplishes and why.>

## Changes

<One bullet group per logical change (merge commits that belong together). Say what changed and
 why, with file paths where they help a reviewer.>

## Breaking Changes

<Only when something breaks: what, why, and what consumers must do. Otherwise omit the heading.>
```

## Hard rules

- Read every commit body and the diff; never summarise from subjects alone.
- No test-plan or QA checklist section.
- No `Co-Authored-By`, no "Generated with", no attribution footers of any kind.
- Never force-push. Never open the PR against a branch other than the detected base unless the
  user names one.

## Output

Report the PR URL and its title.
