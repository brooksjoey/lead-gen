@echo off
REM Alias: lg-test-system -> lg-verify-all
call lg-verify-all.bat %*
exit /b %ERRORLEVEL%

