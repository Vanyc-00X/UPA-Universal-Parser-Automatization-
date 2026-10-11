<#
.SYNOPSIS
    Запуск UPA: API (FastAPI) + веб-интерфейс (Vite) одной командой.

.DESCRIPTION
    Скрипт проверяет окружение, при необходимости создаёт схему БД, проверяет
    доступность локальной ИИ-модели (Ollama) и поднимает оба процесса. Закрытие
    окна или Ctrl+C останавливает и API, и фронтенд.

    Если ИИ-модель недоступна, приложение всё равно запускается: анализ страниц
    деградирует до детерминированных эвристик и ручного выбора элементов.

.PARAMETER SkipFrontend
    Поднять только API.

.PARAMETER SkipInstall
    Не устанавливать зависимости, даже если окружение не готово.

.PARAMETER Headed
    Показать окно браузера (полезно для сайтов за логином). Влияет на Этап 1.

.PARAMETER PullModel
    Если Ollama доступна, а модель из настроек отсутствует — выполнить ollama pull.

.EXAMPLE
    .\run.ps1
    .\run.ps1 -Headed
    .\run.ps1 -SkipFrontend
    .\run.ps1 -PullModel

.NOTES
    Первый запуск занимает несколько минут: создание venv и установка зависимостей.
#>

[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipInstall,
    [switch]$Headed,
    [switch]$PullModel
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --- Пути и константы --------------------------------------------------------

$RepoRoot = $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$VenvDir = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$ApiUrl = 'http://127.0.0.1:8000'
$WebUrl = 'http://127.0.0.1:5173'
$OllamaUrl = 'http://127.0.0.1:11434'

function Write-Step { param([string]$Text) Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok { param([string]$Text) Write-Host "    $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "    $Text" -ForegroundColor Yellow }
function Write-Err { param([string]$Text) Write-Host "    $Text" -ForegroundColor Red }

# --- Окружение ---------------------------------------------------------------

function Test-Port {
    param([string]$Url, [int]$TimeoutSec = 2)
    try {
        Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-CommandPath {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

Write-Step 'Проверяю окружение'

$pythonExe = $null
if (Test-Path $VenvPython) {
    $pythonExe = $VenvPython
    Write-Ok "Виртуальное окружение: $VenvDir"
} else {
    $systemPython = Get-CommandPath @('python', 'py')
    if (-not $systemPython) {
        Write-Err 'Python не найден. Установите Python 3.10+ и добавьте его в PATH.'
        exit 1
    }
    if ($SkipInstall) {
        Write-Err 'Нет .venv, а установка отключена ключом -SkipInstall.'
        exit 1
    }
    Write-Ok "Системный Python: $systemPython"
    Write-Step 'Создаю виртуальное окружение'
    & $systemPython -m venv $VenvDir
    $pythonExe = $VenvPython
}

$pipCheck = & $pythonExe -c "import fastapi, uvicorn, sqlalchemy; print('deps-ready')" 2>$null
if ($pipCheck -ne 'deps-ready') {
    if ($SkipInstall) {
        Write-Err 'Зависимости бэкенда не установлены, установка отключена ключом -SkipInstall.'
        exit 1
    }
    Write-Step 'Устанавливаю зависимости бэкенда (первый раз это занимает несколько минут)'
    & $pythonExe -m pip install --upgrade pip --quiet
    & $pythonExe -m pip install -e "$BackendDir[dev]" --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Не удалось установить зависимости бэкенда.'
        exit 1
    }
    Write-Ok 'Зависимости бэкенда установлены'
} else {
    Write-Ok 'Зависимости бэкенда на месте'
}

# --- Схема базы данных -------------------------------------------------------

Write-Step 'Готовлю базу данных'
Push-Location $BackendDir
try {
    & $pythonExe -m app init-db
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Не удалось инициализировать БД.'
        exit 1
    }
} finally {
    Pop-Location
}

# --- Локальная ИИ-модель -----------------------------------------------------

Write-Step 'Проверяю локальную ИИ-модель (Ollama)'
$llmReady = $false
$WantedModel = if ($env:UPA_OLLAMA_MODEL) { $env:UPA_OLLAMA_MODEL } else { 'qwen2.5:7b' }
try {
    $tags = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 3 -ErrorAction Stop
    $modelNames = @($tags.models | ForEach-Object { $_.name })
    $hasWanted = $modelNames | Where-Object { $_ -eq $WantedModel -or $_.StartsWith("$WantedModel:") }
    if ($hasWanted) {
        $llmReady = $true
        Write-Ok "Ollama доступна, модель $WantedModel на месте"
    } elseif ($modelNames.Count -gt 0) {
        Write-Warn "Ollama доступна, но нет $WantedModel (есть: $($modelNames[0])). Запуск с эвристиками."
        if ($PullModel) {
            Write-Step "Загружаю модель $WantedModel (это может занять несколько минут)"
            $ollamaExe = Get-CommandPath @('ollama')
            if ($ollamaExe) {
                & $ollamaExe pull $WantedModel
                if ($LASTEXITCODE -eq 0) {
                    $llmReady = $true
                    Write-Ok "Модель $WantedModel загружена"
                } else {
                    Write-Warn "Не удалось выполнить ollama pull $WantedModel — продолжаю без ИИ"
                }
            } else {
                Write-Warn 'Команда ollama не в PATH — загрузите модель вручную или через UI'
            }
        } else {
            Write-Warn "Чтобы подтянуть модель: .\run.ps1 -PullModel   или   ollama pull $WantedModel"
        }
    } else {
        Write-Warn "Ollama доступна, но модели не загружены: ollama pull $WantedModel"
        if ($PullModel) {
            Write-Step "Загружаю модель $WantedModel"
            $ollamaExe = Get-CommandPath @('ollama')
            if ($ollamaExe) {
                & $ollamaExe pull $WantedModel
                if ($LASTEXITCODE -eq 0) { $llmReady = $true; Write-Ok "Модель $WantedModel загружена" }
            }
        }
    }
} catch {
    Write-Warn 'Ollama недоступна — приложение запустится без ИИ (ручной выбор элементов).'
}

# --- Браузер для съёмки страниц (Этап 1) -------------------------------------
#
# Chromium хранится внутри репозитория, а не в профиле пользователя: так его
# гарантированно видит и API, и любой скрипт проверки. Переменную наследуют
# дочерние процессы, поэтому выставляем её до запуска API.

Write-Step 'Готовлю браузер для съёмки страниц'

$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $RepoRoot 'data\_pw-browsers'
# Временные файлы браузера тоже уводим в репозиторий: в ограниченных окружениях
# запись в системный %TEMP% может быть запрещена, и запуск браузера падает.
$browserTmp = Join-Path $RepoRoot 'data\_tmp'
New-Item -ItemType Directory -Force -Path $env:PLAYWRIGHT_BROWSERS_PATH, $browserTmp | Out-Null
$env:TEMP = $browserTmp
$env:TMP = $browserTmp

$chromiumPresent = @(Get-ChildItem $env:PLAYWRIGHT_BROWSERS_PATH -Directory -Filter 'chromium*' -ErrorAction SilentlyContinue).Count -gt 0
if (-not $chromiumPresent) {
    if ($SkipInstall) {
        Write-Warn 'Chromium не установлен, установка отключена ключом -SkipInstall.'
        Write-Warn 'Съёмка страниц будет недоступна до: python -m playwright install chromium'
    } else {
        Write-Ok 'Скачиваю Chromium (около 120 МБ, только при первом запуске)'
        Push-Location $BackendDir
        try {
            & $pythonExe -m playwright install chromium
            if ($LASTEXITCODE -ne 0) {
                Write-Warn 'Не удалось скачать Chromium. Приложение запустится, но съёмка страниц будет недоступна.'
                Write-Warn 'Повторите позже: python -m playwright install chromium'
            } else {
                Write-Ok 'Chromium установлен'
            }
        } finally {
            Pop-Location
        }
    }
} else {
    Write-Ok "Chromium на месте: $env:PLAYWRIGHT_BROWSERS_PATH"
}

# --- Запуск процессов --------------------------------------------------------

if (Test-Port "$ApiUrl/health" -TimeoutSec 1) {
    Write-Warn "Порт API уже занят: $ApiUrl (используется существующий процесс)"
    $apiProcess = $null
} else {
    Write-Step 'Запускаю API'
    $apiArgs = @('-m', 'app', 'serve', '--host', '127.0.0.1', '--port', '8000')
    $apiProcess = Start-Process -FilePath $pythonExe -ArgumentList $apiArgs `
        -WorkingDirectory $BackendDir -PassThru -NoNewWindow
}

$webProcess = $null
if (-not $SkipFrontend) {
    if (Test-Port $WebUrl -TimeoutSec 1) {
        Write-Warn "Порт интерфейса уже занят: $WebUrl (используется существующий процесс)"
    } else {
        $nodeExe = Get-CommandPath @('node')
        if (-not $nodeExe) {
            Write-Warn 'Node.js не найден — интерфейс не будет запущен. API доступен по адресу ' + $ApiUrl
        } else {
            $pnpmPath = Get-CommandPath @('pnpm')
            if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
                if ($SkipInstall) {
                    Write-Warn 'Нет node_modules, установка отключена ключом -SkipInstall.'
                } else {
                    Write-Step 'Устанавливаю зависимости интерфейса'
                    Push-Location $FrontendDir
                    try {
                        if ($pnpmPath) {
                            $pnpmDir = Split-Path $pnpmPath -Parent
                            $env:PATH = "$pnpmDir;$env:PATH"
                            & $nodeExe $pnpmPath install --silent
                        } else {
                            & $nodeExe (Join-Path (Split-Path $nodeExe -Parent) 'npm.cmd') install --silent
                        }
                    } finally {
                        Pop-Location
                    }
                }
            }
            if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
                Write-Step 'Запускаю веб-интерфейс'
                $nodeDir = Split-Path $nodeExe -Parent
                $viteScript = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
                $webProcess = Start-Process -FilePath $nodeExe -ArgumentList @($viteScript) `
                    -WorkingDirectory $FrontendDir -PassThru -NoNewWindow
            } else {
                Write-Warn 'Зависимости интерфейса не установлены — запускаю только API.'
            }
        }
    }
}

# --- Ожидание готовности -----------------------------------------------------

Write-Step 'Жду готовности API'
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    if (Test-Port "$ApiUrl/health" -TimeoutSec 2) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if ($ready) { Write-Ok "$ApiUrl/health отвечает" } else { Write-Warn 'API не ответил за 30 секунд — смотрите вывод процесса выше' }

# --- Итог --------------------------------------------------------------------

Write-Host ''
Write-Host '------------------------------ UPA запущена ------------------------------' -ForegroundColor Cyan
Write-Host "  Веб-интерфейс : $WebUrl"
Write-Host "  API           : $ApiUrl"
Write-Host "  Документация  : $ApiUrl/docs"
Write-Host "  ИИ-модель     : $(if ($llmReady) { 'доступна' } else { 'недоступна (работа без ИИ)' })"
Write-Host '  Остановка     : Ctrl+C'
Write-Host '-------------------------------------------------------------------------' -ForegroundColor Cyan
Write-Host ''

if ($Headed) { Write-Warn 'Ключ -Headed учтён: браузер на Этапе 1 будет запускаться с окном.' }

# --- Уборка процессов --------------------------------------------------------

function Stop-ChildProcess {
    param($Process, [string]$Name)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            Write-Host "    Останавливаю $Name (PID $($Process.Id))" -ForegroundColor DarkGray
            # Дочерние процессы uvicorn/vite завершаем вместе с родителем.
            & taskkill /PID $Process.Id /T /F 2>$null | Out-Null
        }
    } catch {
        Write-Warn "Не удалось корректно остановить $Name"
    }
}

try {
    if ($webProcess) { Wait-Process -Id $webProcess.Id }
    elseif ($apiProcess) { Wait-Process -Id $apiProcess.Id }
    else { Write-Host 'Оба порта были заняты — нечего останавливать.' }
} finally {
    Write-Host ''
    Write-Step 'Останавливаю UPA'
    Stop-ChildProcess -Process $webProcess -Name 'интерфейс'
    Stop-ChildProcess -Process $apiProcess -Name 'API'
    Write-Ok 'Готово'
}
