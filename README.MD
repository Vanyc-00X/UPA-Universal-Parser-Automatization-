<p align="center">
  <img src="docs/assets/upa-banner.svg" alt="UPA — Universal Parser Automatization" width="100%">
</p>

<h1 align="center">UPA — Universal Parser Automatization</h1>

<p align="center">
  <strong>Локальный конструктор сценариев для сайтов:</strong><br>
  изучить страницу → сохранить рецепт → собирать данные или заполнять формы пачками.
</p>

<p align="center">
  <a href="#кому-это-нужно">Кому нужно</a> ·
  <a href="#почему-upa-а-не-ещё-один-парсер">Почему UPA</a> ·
  <a href="#пример-использования-за-5-минут">Пример за 5 минут</a> ·
  <a href="#быстрый-старт">Старт</a> ·
  <a href="docs/disclaimer.md">Дисклеймер</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-UI-61DAFB?style=flat-square&logo=react&logoColor=black">
  <img alt="Playwright" src="https://img.shields.io/badge/Playwright-Browser-2EAD33?style=flat-square&logo=playwright&logoColor=white">
  <img alt="Local-first" src="https://img.shields.io/badge/Local--first-No%20cloud%20lock--in-4C8DFF?style=flat-square">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-run.ps1%20%2F%20launch.cmd-0078D4?style=flat-square&logo=windows&logoColor=white">
</p>

---

## Одной фразой

**UPA превращает «я каждый раз руками лазаю по сайту» в переиспользуемый сценарий** — с версиями, отчётом о дырах в данных, самопочинкой селекторов и безопасным dry-run перед отправкой форм.

Данные остаются на вашем ПК. ИИ (Ollama) помогает, но **не обязателен**.

---

## Кому это нужно

| Вам зайдёт, если… | Вам, скорее всего, не нужно, если… |
|---|---|
| Нужно регулярно снимать каталоги, прайсы, вакансии, новости | Нужен разовый `curl` / одноразовый скрипт на 20 строк |
| Хотите **сценарий как актив**: версии, повторный запуск, экспорт | Ищете облачный SaaS-парсер «под ключ» без локальной установки |
| Формы нужно заполнять из CSV/Excel на десятки строк | Нужен скрытый обход капчи / антибота «на автомате» |
| Важны приватность и контроль: локально, без отправки HTML в чужой облачный парсер | Нужен только API-клиент к уже известному JSON endpoint |
| После смены вёрстки хотите **предложение патча**, а не мёртвый скрипт | Не готовы соблюдать ToS сайтов и отвечать за live-отправки |

> Короткий тест: если вы уже второй раз копируете селекторы в новый скрипт — UPA для вас.

---

## Почему UPA, а не «ещё один парсер»

Большинство инструментов останавливаются на «скачал HTML → вытащил поля».  
UPA заточен под **жизнь сценария после первой удачи**:

| Проблема | Как решает UPA |
|---|---|
| Скрипт сломался через неделю | Self-healing: предлагает новый селектор, **не применяет молча** |
| Непонятно, собрали всё или с дырами | Отчёт о полноте по каждому запуску |
| Нужно и парсить, и заводить данные | Два режима: `collection` (сбор) и `form_fill` (ввод) |
| Страшно жать «Отправить» на 50 строк | Dry-run по DOM + явное подтверждение опасных действий |
| Хочется унести автоматизацию без приложения | Экспорт самостоятельного Playwright `.py` |
| Не хочется облако | Local-first: SQLite + артефакты на диске, ИИ опционален |

```text
URL ──► снапшот (DOM / скрин / сеть)
          │
          ▼
     карта элементов + редактор
          │
          ├─► сценарий сбора ──► запуск ──► CSV / XLSX / JSON / ТЗ.md
          │                         │
          │                         └─► healing (propose → confirm)
          │
          └─► воркфлоу ввода ◄── CSV/XLSX
                    │
                    ├─► dry-run (без отправки)
                    └─► live / export .py
```

---

## Пример использования за 5 минут

Полный разбор: [`examples/DEMO.md`](examples/DEMO.md)

### A) Собрать каталог в таблицу

```powershell
.\run.ps1
```

1. **Сайты** → URL каталога → «Снять снапшот»  
2. **Карта элементов** → поля `title`, `price`, `url` → сохранить сценарий  
3. **Сценарии** → «Запустить» → **Запуски** → экспорт CSV  

Готовый каркас сценария:

```json
{
  "url": "https://shop.example.com/catalog",
  "title": "Каталог товаров",
  "plan": { "mode": "list", "item_selector": ".product-card" },
  "pagination": { "kind": "next_link", "selector": "a.pagination__next", "max_pages": 5 },
  "fields": [
    { "key": "title", "title": "Название", "selector": ".product-card__title", "required": true },
    { "key": "price", "title": "Цена", "selector": ".product-card__price" },
    {
      "key": "url",
      "title": "Ссылка",
      "selector": "a.product-card__link",
      "strategy": "attribute",
      "attribute": "href"
    }
  ]
}
```

Файл: [`examples/catalog-scenario.json`](examples/catalog-scenario.json)

### B) Заполнить форму из CSV (с безопасным прогоном)

```csv
name,email,city
Иван,ivan@example.com,msk
Мария,maria@example.com,spb
```

```json
{
  "url": "https://forms.example.com/order",
  "title": "Форма заявки",
  "steps": [
    { "type": "goto", "url": "https://forms.example.com/order" },
    { "type": "fill", "selector": "#field-name", "value": "{{name}}" },
    { "type": "fill", "selector": "#field-email", "value": "{{email}}" },
    { "type": "select", "selector": "#field-city", "value": "{{city}}" },
    { "type": "click", "selector": "#btn-submit", "confirm_required": true }
  ]
}
```

1. **Воркфлоу** → вставьте шаги / запись JSON  
2. CSV → **Dry-run** (форма не уходит)  
3. При необходимости → **Live** с галочкой подтверждения  
4. **Экспорт .py** — тот же сценарий без UPA  

Файлы: [`examples/form-workflow.json`](examples/form-workflow.json) · [`examples/params-form.csv`](examples/params-form.csv)

### C) Через API (для автоматизации)

```http
POST /api/v1/snapshots
{ "url": "https://shop.example.com/catalog" }

POST /api/v1/runs
{ "scenario_id": "<id>", "min_coverage": 0.9 }

POST /api/v1/workflows/{id}/dry-run
{ "snapshot_id": "<id>", "csv_text": "name,email,city\n..." }
```

OpenAPI после запуска: http://127.0.0.1:8000/docs

---

## Быстрый старт

**Windows (рекомендуется):**

```powershell
git clone https://github.com/Vanyc-00X/UPA-Universal-Parser-Automatization-.git
cd UPA-Universal-Parser-Automatization-
.\run.ps1
```

Или двойной клик по [`launch.cmd`](launch.cmd). Ярлык на рабочий стол:

```powershell
.\scripts\create-shortcut.ps1
```

| Что | Адрес |
|---|---|
| Веб-интерфейс | http://127.0.0.1:5173 |
| API | http://127.0.0.1:8000 |
| Документация API | http://127.0.0.1:8000/docs |

**Без ИИ всё работает.** Ollama усиливает анализ страниц:

```powershell
.\run.ps1 -PullModel
# или в UI: Обзор → «Загрузить модель»
```

**Docker (API):**

```powershell
docker compose up --build
```

Подробнее: [docs/quickstart.md](docs/quickstart.md)

---

## Что внутри

| Возможность | Зачем вам |
|---|---|
| Снапшот Playwright | DOM, скрин, сеть, storage state — воспроизводимая база |
| Карта элементов + редактор | Видно, что именно парсим, до первого запуска |
| Версии сценариев | Правка вёрстки ≠ потеря работы |
| Отчёт о полноте | Сразу видно дыры в обязательных полях |
| Self-healing | Предложение патча селекторов без автоприменения |
| Воркфлоу + CSV/XLSX | «500 строк — заведи на сайте» |
| Dry-run / confirm | Меньше случайных отправок и платежей |
| Экспорт Playwright | Сценарий живёт отдельно от UPA |
| Шаблоны | Каталог, форма, статья — старт не с нуля |

Шаблоны в UI (**Шаблоны**) и `GET /api/v1/templates`. Примеры в [`examples/`](examples/).

---

## Документация

| Документ | О чём |
|---|---|
| [Быстрый старт](docs/quickstart.md) | Установка и первый сценарий |
| [Сценарии и воркфлоу](docs/scenarios.md) | Сбор, ввод, запись, loop/if |
| [Демо](examples/DEMO.md) | Пошаговый пример «как пользоваться» |
| [FAQ: блокировки](docs/faq-blocking.md) | 403, капча, robots, healing |
| [Ретенция данных](docs/data-retention.md) | Что хранится локально |
| [Дисклеймер](docs/disclaimer.md) | ToS и ответственность |
| [PLAN.md](PLAN.md) | Этапы разработки 0–8 |

---

## Стек

`Python` · `FastAPI` · `Playwright` · `SQLite` · `React` · опционально `Ollama`

---

## Дисклеймер

UPA — инструмент для **осознанной** автоматизации. Соблюдайте Terms of Service сайтов,
robots.txt и закон. Live-воркфлоу может отправлять формы и инициировать заказы/платежи —
подтверждение опасных шагов есть, но ответственность за запуск на вас.

Подробнее: [docs/disclaimer.md](docs/disclaimer.md)

---

<p align="center">
  <sub>Сделано как local-first альтернатива одноразовым парсерам.<br>
  Если сценарий должен жить дольше одной недели — вам сюда.</sub>
</p>
