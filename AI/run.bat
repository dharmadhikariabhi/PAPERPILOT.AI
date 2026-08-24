@echo off
title PaperPilot.AI Launcher
echo Installing / Checking Libraries...
py -m pip install flask google-generativeai pypdfium2 Pillow requests || python -m pip install flask google-generativeai pypdfium2 Pillow requests
echo.
echo Starting PaperPilot.AI...
py app.py || python app.py
pause