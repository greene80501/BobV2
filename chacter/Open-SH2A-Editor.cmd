@echo off
setlocal
set "ROOT=%~dp0"
python "%ROOT%tools\sh2a_editor.py" "%ROOT%bob_tui_ansi.sh"
