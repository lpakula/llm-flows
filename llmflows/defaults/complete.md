# COMPLETE

## PURPOSE

Summarize everything important from this execution and save it for future reference.

## WORKFLOW

1. Review all changes you made during this execution
2. Write a summary using the structure below
3. Save it using a heredoc so formatting is preserved:
   ```
   llmflows run complete --summary "$(cat <<'EOF'
   ## What was done

   Brief description of the overall goal accomplished.

   ## Changes

   - `path/to/file.ext` — what changed and why
   - `path/to/other.ext` — what changed and why

   ## Notes

   Any decisions, trade-offs, issues encountered, or remaining work.
   EOF
   )"
   ```

## RULES

- Use the heredoc format above — do NOT put everything on one line
- Use markdown: bullet points, backtick file paths, short paragraphs
- Be specific about file names and what changed in each
- After running `llmflows run complete`, **stop** -- do not run any other commands

---
**YOU MUST FOLLOW THE WORKFLOW ABOVE.**
This is the final step. Run `llmflows run complete` with your summary, then stop.
