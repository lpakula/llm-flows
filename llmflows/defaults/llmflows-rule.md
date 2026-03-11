---
description: Core protocol for llmflows-managed agents
globs:
alwaysApply: true
---

# llmflows Agent Protocol

You are a llmflows-managed agent working in a git worktree.

## Commands

- `llmflows mode next` -- get your next step instructions
- `llmflows mode current` -- re-read the current step (use after crash/restart)

## Rules

1. Always run `llmflows mode next` to get step instructions -- never guess
2. Complete each step fully before moving to the next
3. After completing a step, run `llmflows mode next` to continue
