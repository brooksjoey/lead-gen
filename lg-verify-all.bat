@echo off
python cli\lg_verify_all.py %*
exit /b %ERRORLEVEL%

