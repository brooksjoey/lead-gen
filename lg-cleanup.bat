@echo off
REM Alias: lg-cleanup -> lg-reset-test-data
call lg-reset-test-data.bat %*
exit /b %ERRORLEVEL%

