@echo off
REM Main CLI entry point: lg <command> [args]
python cli\cli.py %*
exit /b %ERRORLEVEL%

