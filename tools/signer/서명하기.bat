@echo off
chcp 65001 > nul
python -I "%~dp0signer.py" sign
pause
