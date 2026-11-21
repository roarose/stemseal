@echo off
chcp 65001 > nul
python "%~dp0signer.py" sign
pause
