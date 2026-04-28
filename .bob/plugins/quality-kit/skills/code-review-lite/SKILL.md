---
name: code-review-lite
description: Run a quick bug-focused review and extract the main quality issues.
user-invocable: true
allowed-tools:
  - text_utils__summarize_text
  - text_utils__extract_todos
  - text_utils__word_stats
---

Use this skill when the user asks for a quick review, a summary of findings, or obvious TODO extraction.

Recommended sequence:
1. Summarize the relevant notes or diff with `text_utils__summarize_text`.
2. Extract actionable follow-ups with `text_utils__extract_todos`.
3. Use `text_utils__word_stats` only if the user wants a compact density or size readout.

Prioritize correctness issues, regressions, and missing tests.

Review focus: $ARGUMENTS
