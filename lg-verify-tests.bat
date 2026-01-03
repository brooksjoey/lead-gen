@echo off
python cli\lg_verify_tests.py %*
exit /b %ERRORLEVEL%

