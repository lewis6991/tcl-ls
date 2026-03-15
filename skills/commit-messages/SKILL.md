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
- Prefer amending related unmerged commits; use a new commit only for
  unrelated changes.
- Preserve existing commit boundaries unless the user asks to change
  them.
