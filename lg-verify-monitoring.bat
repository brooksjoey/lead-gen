@echo off
python cli\lg_verify_monitoring.py %*
exit /b %ERRORLEVEL%

