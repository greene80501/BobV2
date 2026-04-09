@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%img.ANS" (
    start "" "%ROOT%moebius\Moebius.exe" "%ROOT%img.ANS"
) else (
    start "" "%ROOT%moebius\Moebius.exe"
)
