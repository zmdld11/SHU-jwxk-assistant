@echo off
chcp 65001 >nul
title 安装 Python 运行环境
echo ========================================================
echo        上大选课监控和抢课助手 - 环境安装脚本
echo ========================================================
echo.
echo 正在检测 Python 环境...
python --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先官网下载安装并勾选 "Add Python to PATH"（建议版本：Python 3.8 - 3.12）。
    echo 按任意键退出...
    pause >nul
    exit
)

for /f "tokens=2" %%I in ('python --version 2^>^&1') do echo [成功] 检测到 Python 版本: %%I

echo.
echo 正在检查配置文件...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [成功] 已自动从 .env.example 初始化 .env 配置文件。
        echo 请记得在 .env 文件中填入你的教务系统 Cookie 等信息！
    ) else (
        echo [警告] 缺少 .env.example，请手动创建 .env 文件进行配置。
    )
) else (
    echo [提示] .env 配置文件已存在。
)

echo.
echo 正在设置隔离的虚拟环境 (Virtual Environment)...
if not exist ".venv" (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败。
        pause >nul
        exit
    )
    echo [成功] 已创建 .venv 虚拟环境，不会污染全局 base 环境。
) else (
    echo [提示] .venv 虚拟环境已存在。
)

echo.
echo [准备就绪] 正在进入虚拟环境，并使用清华镜像源安装第三方依赖...
echo 这可能需要一两分钟，请耐心等待。
echo.

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>nul
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo ========================================================
if %errorlevel% equ 0 (
    echo [成功] 所有依赖库安装完成！
    echo 你现在可以双击运行“启动系统.bat”了。
) else (
    echo [失败] 安装过程中出现错误，请检查网络或确认 requirements.txt 是否存在。
)
echo ========================================================
echo 按任意键退出...
pause >nul
