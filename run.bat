@echo off
REM 激活 Conda 环境
call conda activate myenv

REM 运行脚本
python ChaturbateRecorder.py

REM 暂停，保持窗口打开
pause
