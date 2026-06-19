@echo off
chcp 65001 >nul
title Novel Speaker Labeling - Local OpenCode + oh-my-openagent

echo ============================================
echo  小说对话说话人标注系统
echo  引擎: OpenCode v1.17.8 (本地)
echo  插件: oh-my-openagent v4.11.1 (本地)
echo  模型: Ollama qwen3:4b
echo  服务器: http://172.31.102.162:11434
echo ============================================

:: ===== 隔离配置 =====
set OPENCODE_CONFIG_DIR=E:\projects\novalSpeakerV3\.opencode-home
set OPENCODE_DISABLE_AUTOUPDATE=1
set OPENCODE_DISABLE_PRUNE=1
set OPENCODE_PURE=1

:: ===== 检查 Ollama 服务 =====
echo.
echo [检查] Ollama 服务状态...
curl -s http://172.31.102.162:11434/api/tags >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] Ollama 服务不可用！请检查服务器 172.31.102.162
    pause
    exit /b 1
)
echo [OK] Ollama 服务正常

:: ===== 检查模型 =====
echo [检查] qwen3:4b 模型...
curl -s http://172.31.102.162:11434/api/tags | findstr "qwen3:4b" >nul
if %ERRORLEVEL% neq 0 (
    echo [错误] qwen3:4b 模型未找到！
    pause
    exit /b 1
)
echo [OK] qwen3:4b 模型已就绪

:: ===== 检查 labeled.txt 进度 =====
echo [检查] 已有标注进度...
if exist "labeled.txt" (
    for /f %%i in ('type labeled.txt ^| find /c /v ""') do set LABELED=%%i
) else (
    set LABELED=0
)
echo [信息] 已有 %LABELED% 条标注，剩余 %DIALOGUES% 条
echo.

:: ===== 检查 AGENTS.md =====
if not exist "AGENTS.md" (
    echo [警告] AGENTS.md 不存在！标注规则将不会被加载。
)

:: ===== 启动 OpenCode =====
echo [启动] OpenCode (本地源码)...
echo.
cd /d E:\projects\novalSpeakerV3\opencode

bun run --cwd packages/opencode dev ^
    --dangerously-skip-permissions

echo.
echo 标注已完成！
pause
