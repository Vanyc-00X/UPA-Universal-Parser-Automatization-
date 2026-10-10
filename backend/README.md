# UPA — backend

Локальный API приложения UPA: FastAPI + SQLite + Playwright (Этап 1).

## Быстрый старт

```powershell
# из каталога backend/
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
python -m app init-db        # создать схему БД
python -m app check          # проверить БД и локальную ИИ-модель
python -m app serve --reload # поднять API на 127.0.0.1:8000
```

Либо просто запустите `..\run.ps1` из корня репозитория — он поднимет и API, и фронтенд.

## Браузер для съёмки страниц

Съёмка страниц (§ Этап 1) требует Chromium. Он ставится один раз и хранится **внутри
репозитория** — в ограниченных окружениях запись в профиль пользователя и системный
`%TEMP%` может быть запрещена, и тогда запуск браузера падает с `EPERM`.

```powershell
# из корня репозитория
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\data\_pw-browsers"
$env:TEMP = "$PWD\data\_tmp"; $env:TMP = $env:TEMP
.\.venv\Scripts\python -m playwright install chromium
```

`run.ps1` выставляет эти переменные сам и скачивает браузер при первом запуске.
Проверить, что всё работает, можно скриптом `..\tools\check_browser.py`: он поднимает
локальный стенд и проверяет снапшот по 30 пунктам.

Если загрузка браузера через Playwright не удаётся (таймаут, обрыв потока), файл можно
взять напрямую и распаковать в `data\_pw-browsers\chromium_headless_shell-<ревизия>\`.
Актуальный адрес печатает сам установщик:

```powershell
$env:DEBUG = 'pw:install'
python -m playwright install chromium-headless-shell
```

## Установка зависимостей без pip-резолвера

Если `pip install` зависает на переборе версий (симптом: кэш растёт, а установка не
начинается), используйте точные версии и локальные колёса:

```powershell
python ..\tools\fetch_wheels.py --out data/_wheels
.\.venv\Scripts\python -m pip install --no-index --no-deps (Get-ChildItem ..\data\_wheels\*.whl).FullName
```

`tools/fetch_wheels.py` обходит pip-резолвер: разбирает только **обязательные**
зависимости (без `extras`), выбирает колёса под текущую версию Python и складывает их в
один каталог. Для запуска тестов и приложения этого достаточно.

## Команды CLI

| Команда | Назначение |
|---|---|
| `python -m app init-db` | создать каталоги данных и схему БД |
| `python -m app check` | проверить БД и доступность Ollama; код возврата 1 при сбое БД |
| `python -m app info` | показать действующие настройки (без секретов) |
| `python -m app serve` | запустить uvicorn (`--host`, `--port`, `--reload`) |

## Тесты и линтеры

```powershell
python -m pytest
python -m ruff check app tests
python -m black --check app tests
```

## Эндпоинты Этапа 0

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | состояние приложения и подсистем (всегда 200, если процесс жив) |
| GET | `/api/v1/system/info` | сведения о сборке и настройках |
| GET | `/api/v1/system/features` | готовность функций по этапам |
| GET | `/api/v1/system/roadmap` | этапы разработки из PLAN.md |
| GET | `/api/v1/system/llm` | состояние локальной ИИ-модели |

Все маршруты доступны и без префикса `/api/v1`. Интерактивная документация — `/docs`.

## Структура

```
app/
├─ api/         # роутеры, схемы, обработчики ошибок
├─ core/        # конфигурация, логирование, ошибки, доступ к БД
├─ storage/     # ORM-модели
├─ crawler/     # Playwright и снапшоты (Этап 1)
├─ analyzer/    # анализ и карта элементов (Этап 2)
├─ engine/      # движок извлечения (Этап 4)
├─ exporters/   # выгрузки (Этап 5)
└─ cli.py       # консольные команды
```

## Соглашения

- **Ошибки.** Любая ожидаемая проблема выражается наследником `UPAError` и превращается
  в единый JSON `{"error": {"code", "message", "details"}}`.
- **Настройки.** Только через переменные окружения `UPA_*` и `.env` в корне репозитория.
- **Работа без ИИ.** Недоступная модель — штатное состояние: приложение обязано
  оставаться работоспособным, анализ деградирует до детерминированных эвристик.
