---
name: repo-orienter
description: Inspect repository structure and summarize the most relevant files before making changes.
user-invocable: true
allowed-tools:
  - repo_inspector__list_files
  - repo_inspector__read_file_head
  - repo_inspector__find_in_files
---

Use the repo inspection MCP tools first when the user asks what a project does, where code lives, or what files matter.

Recommended sequence:
1. Call `repo_inspector__list_files` to map the repository.
2. Call `repo_inspector__find_in_files` for the user's topic or subsystem.
3. Call `repo_inspector__read_file_head` on the most relevant files.

When you answer, give a short structure summary, key entry points, and the next practical action.

User focus: $ARGUMENTS
