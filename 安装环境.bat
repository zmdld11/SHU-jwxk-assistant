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
    echo [错误] 未检测到 Python，请先官网下载安装并勾选 "Add Python to PATH"。
    echo 按任意键退出...
    pause >nul
    exit
)

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
echo [准备就绪] 正在使用清华大学镜像源加速安装必需的第三方库...
echo 这可能需要一两分钟，请耐心等待。
echo.

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
