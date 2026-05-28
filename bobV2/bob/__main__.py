import sys

# Windows uses cp1252 as the default file encoding. LiteLLM opens tokenizer
# JSON files via importlib.resources without specifying encoding='utf-8',
# which raises UnicodeDecodeError. The only reliable fix is to run Python
# in UTF-8 mode (-X utf8), which must be set before any imports happen.
# If we're on Windows and not already in UTF-8 mode, re-exec immediately.
if sys.platform == "win32" and not sys.flags.utf8_mode:
    import os
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "bob"] + sys.argv[1:],
            env=os.environ,
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)

from bob.cli.main import cli_main

cli_main()
