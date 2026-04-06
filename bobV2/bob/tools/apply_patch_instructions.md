# apply_patch Tool Instructions

The `apply_patch` tool accepts a **custom patch format** that is more readable and
easier to generate than unified diff.  This document is the complete specification.

---

## Envelope

Every patch must be wrapped in the following envelope:

```
*** Begin Patch
<patch body>
*** End Patch
```

The tool will reject any input that does not start with `*** Begin Patch` and end
with `*** End Patch` (after stripping leading/trailing whitespace).

---

## File Operations

### Add File

Creates a new file.  Every line of the new file content is prefixed with `+`.

```
*** Add File: path/to/new_file.py
+line one of new file
+line two of new file
+line three of new file
```

Rules:
- The path is relative to the **repository root** (the directory containing the
  `.git` folder, or the cwd if no `.git` is present).
- The `+` prefix is stripped before writing; it is **not** part of the file content.
- The file must not already exist.  If it does, the patch will fail.

### Update File

Modifies an existing file using one or more **hunks**.

```
*** Update File: path/to/existing_file.py
@@ ... @@
 context line (unchanged)
 context line (unchanged)
-line to remove
-another line to remove
+replacement line
+another replacement line
 context line (unchanged)
```

Rules:
- After the `*** Update File:` header there may be an optional `Move to:` directive
  (see below).
- Each hunk begins with `@@ ... @@` (the `...` is ignored by the parser — it is
  present for human readability only, as in standard unified diff).
- Lines prefixed with a **space** are context lines — they must match the file
  exactly and are not changed.
- Lines prefixed with `-` are removed.
- Lines prefixed with `+` are inserted.
- At least **two context lines** should surround each change so the hunk can be
  located unambiguously, except at the very beginning or end of a file.
- Multiple hunks are allowed in a single `*** Update File` block.

### Delete File

Deletes an existing file entirely.

```
*** Delete File: path/to/file_to_delete.py
```

No body is needed after the header.

### Move / Rename File

Renames (and optionally modifies) a file.  The `Move to:` directive appears
immediately after the `*** Update File:` line.

```
*** Update File: old/path/module.py
Move to: new/path/module.py
@@ ... @@
 context line
-old line
+new line
 context line
```

If no hunks follow `Move to:` the file is renamed without modification.

---

## Hunk Syntax Reference

```
@@ ... @@
[hunk lines]
```

Each hunk line is exactly one of:

| Prefix | Meaning                        |
|--------|-------------------------------|
| ` `    | Context (unchanged) line       |
| `-`    | Line to delete                 |
| `+`    | Line to insert                 |

There is no line-number information — the tool locates hunks by context matching.
Context is matched **in order** within the file, so hunks must appear in the same
order as the corresponding lines in the source file.

---

## Grammar (BNF)

```
patch          ::= "*** Begin Patch\n" operation+ "*** End Patch\n"

operation      ::= add_file | update_file | delete_file

add_file       ::= "*** Add File: " filepath "\n" add_line+
add_line       ::= "+" any_text "\n"

update_file    ::= "*** Update File: " filepath "\n"
                   move_to?
                   hunk*

move_to        ::= "Move to: " filepath "\n"

delete_file    ::= "*** Delete File: " filepath "\n"

hunk           ::= hunk_header hunk_line+
hunk_header    ::= "@@ " any_text " @@\n"
hunk_line      ::= (" " | "-" | "+") any_text "\n"

filepath       ::= [^\n]+          (* relative path from repo root *)
any_text       ::= [^\n]*
```

---

## Example Patch

The following patch:
1. Creates a new utility module.
2. Updates `main.py` to import from it and fixes a bug.
3. Deletes an obsolete helper file.
4. Renames a module and updates a reference inside it.

```
*** Begin Patch
*** Add File: utils/string_helpers.py
+"""String utility functions."""
+
+
+def truncate(text: str, max_length: int = 80) -> str:
+    """Truncate *text* to *max_length* characters."""
+    if len(text) <= max_length:
+        return text
+    return text[: max_length - 1] + "…"

*** Update File: main.py
@@ ... @@
 import os
 import sys
+from utils.string_helpers import truncate
 
 def run():
@@ ... @@
     result = compute(value)
-    print(result)
+    print(truncate(str(result)))
     return result

*** Delete File: helpers/old_utils.py

*** Update File: helpers/legacy.py
Move to: helpers/compat.py
@@ ... @@
-# Legacy compatibility shim — do not use in new code.
+# Compatibility shim for older call-sites.
 
 from helpers.compat import *  # noqa: F401, F403
*** End Patch
```

---

## Rules and Best Practices

1. **Relative paths only.** All file paths must be relative to the repository root.
   Never use `..` to escape the repository root.

2. **New files use `+` prefix on every line**, including blank lines.  A blank line
   inside a new file is represented as a single `+` with no following text.

3. **Context lines must match exactly**, including leading/trailing whitespace and
   any trailing spaces.  A mismatch causes the hunk to fail.

4. **Order hunks top-to-bottom** within a file.  The tool applies hunks
   sequentially and advances a cursor through the file; a hunk whose context
   appears before the cursor's current position will fail.

5. **No binary files.**  Do not include binary files (images, compiled objects,
   archives, etc.) in a patch.  Use the shell to copy or generate them instead.

6. **Atomic application.**  The tool applies all operations in the patch atomically
   where possible.  If any operation fails, the tool reports the failure and
   no partial changes are written.

7. **Empty files.**  To create an empty file use an `*** Add File:` header with no
   `+` lines.

8. **Line endings.**  The tool normalises line endings to the platform default.
   Do not mix CRLF and LF within a single file.

9. **Encoding.**  All files are read and written as UTF-8.  Non-UTF-8 content must
   be handled with shell tools instead.

10. **Patch size.**  There is no hard limit on patch size, but very large patches
    (thousands of lines) are slow.  Consider breaking a very large change into
    multiple smaller patches applied sequentially.
