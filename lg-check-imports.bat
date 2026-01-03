@echo off
REM Alias: lg-check-imports -> lg-verify-imports
call lg-verify-imports.bat %*
exit /b %ERRORLEVEL%

