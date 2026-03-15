---
name: commit-messages
description: Write, amend, and reword git commit messages for this repo. Use when creating commits, amending unmerged work, rewriting commit history, or checking whether a commit message matches repo policy. Follow Conventional Commits, a 50-character subject limit, 72-character body wrapping, and a detailed body.
---

# Commit Messages

- Inspect the staged or target diff before writing or amending a
  message.
- Use Conventional Commits with `type(scope): summary`; omit the scope
  when it adds no value.
- Prefer `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, and `ci`.
- Keep the subject imperative, omit a trailing period, and keep it at
  50 characters or fewer.
- Add a detailed body and wrap body lines at 72 characters or fewer.
- Before staging or amending, verify every file belongs to the same
  logical change. Leave unrelated edits unstaged or put them in a
  separate commit; do not fold incidental repo-skill or tooling edits
  into a feature commit.
- When invoking `git commit` from the shell, do not rely on `\n`
  escapes inside regular quoted `-m` arguments because they are stored
  literally. Use multiple `-m` flags for separate paragraphs, ANSI-C
  quoting, or `git commit -F <file>` when you need explicit line
  breaks.
- Prefer amending related unmerged commits; use a new commit only for
  unrelated changes.
- Preserve existing commit boundaries unless the user asks to change
  them.
