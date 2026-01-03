@echo off
REM Alias: lg-test-flow -> lg-verify-lead-flow
call lg-verify-lead-flow.bat %*
exit /b %ERRORLEVEL%

