@echo off
REM Startet die FM27 Datenzentrale: überwacht den FM27-Ordner und öffnet die Weboberfläche.
cd /d "%~dp0"
python -m fm27data run --open %*
pause
