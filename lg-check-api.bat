@echo off
REM Alias: lg-check-api -> lg-verify-api-start
call lg-verify-api-start.bat %*
exit /b %ERRORLEVEL%

