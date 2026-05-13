@echo off
:: 设置局部环境变量 (仅对当前命令生效)
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890
echo [Claude CLI] 已通过代理端口 7890 建立隧道...

:: 查找并执行原始 claude 命令
for /f "delims=" %%i in ('where claude') do (
    "%%i" %*
    goto :finish
)
:finish