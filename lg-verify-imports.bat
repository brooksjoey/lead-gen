@echo off
python cli\lg_verify_imports.py %*
exit /b %ERRORLEVEL%

