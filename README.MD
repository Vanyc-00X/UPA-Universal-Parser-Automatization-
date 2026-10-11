<p align="center">
  <img src="docs/assets/upa-banner.svg" alt="UPA — Universal Parser Automatization" width="100%">
</p>

<h1 align="center">UPA — Universal Parser Automatization</h1>

<p align="center">
  <strong>Local-first scenario builder for websites:</strong><br>
  learn a page → save a recipe → collect data or fill forms in batches.
</p>

<p align="center">
  <a href="#who-it-is-for">Who it is for</a> ·
  <a href="#why-upa">Why UPA</a> ·
  <a href="#five-minute-demo">5-minute demo</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/disclaimer.md">Disclaimer</a>
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

## In one sentence

**UPA turns “I keep clicking through this site by hand” into a reusable scenario** — with versions, coverage reports, selector self-healing, change monitoring, and a safe dry-run before form submit.

Your data stays on your machine. Local AI (Ollama) helps with page analysis but is **optional**.

---

## Who it is for

| You’ll like UPA if… | You probably don’t need it if… |
|---|---|
| You regularly scrape catalogs, prices, jobs, news | You need a one-off `curl` / 20-line script |
| You want a **scenario as an asset**: versions, reruns, export | You want a hosted SaaS scraper with zero install |
| You fill forms from CSV/Excel for dozens of rows | You need silent CAPTCHA / antibot bypass |
| Privacy matters: local, no shipping HTML to a third-party scraper | You only need a client for a known JSON API |
| After a layout change you want a **patch proposal**, not a dead script | You’re not ready to respect site ToS / own live submits |

> Quick test: if you’ve copied the same selectors into a new script twice — UPA is for you.

---

## Why UPA

Most tools stop at “download HTML → extract fields”.  
UPA is built for **the life of a scenario after the first win**:

| Pain | What UPA does |
|---|---|
| Script dies after a week | Self-healing proposes a new selector — **never applies silently** |
| Unclear if the run is complete | Coverage report on every run |
| Need both scrape and data entry | `collection` and `form_fill` modes |
| Scary to hit Submit on 50 rows | DOM dry-run + explicit confirm for dangerous steps |
| Want automation without the app | Export a standalone Playwright `.py` |
| Don’t want the cloud | Local-first: SQLite + on-disk artifacts; AI optional |
| Catalog → product page | Two-level **list → detail** collection |
| SPA data lives in XHR | Parse **HTML or XHR/JSON** from the snapshot network log |
| Prices / stock change overnight | **Monitoring** with schedule + run diff |
| Need data elsewhere | Deliver to **webhook / Google Sheets / PostgreSQL** |

```text
URL ──► snapshot (DOM / screenshot / network)
          │
          ▼
     element map + editor
          │
          ├─► collection scenario ──► run ──► CSV / XLSX / JSON / Sheets / webhook / PG
          │                         │
          │                         ├─► healing (propose → confirm)
          │                         └─► monitor (schedule + diff)
          │
          └─► input workflow ◄── CSV/XLSX / live browser recording
                    │
                    ├─► dry-run (no submit)
                    └─► live / export .py
```

---

## Five-minute demo

Full walkthrough: [`examples/DEMO.md`](examples/DEMO.md)

### A) Collect a catalog into a table

```powershell
.\run.ps1
```

1. **Sites** → catalog URL → “Capture snapshot”  
2. **Element map** → fields `title`, `price`, `url` → save scenario  
3. Optional: enable **list → detail** and add product-page fields  
4. **Scenarios** → Run → **Runs** → export CSV (or deliver to Sheets / webhook / Postgres)

Starter scenario: [`examples/catalog-scenario.json`](examples/catalog-scenario.json)

### B) Fill a form from CSV (safe first)

```csv
name,email,city
Ivan,ivan@example.com,msk
Maria,maria@example.com,spb
```

1. **Workflow** → **Record in browser** (or paste JSON)  
2. Load CSV → **Dry-run** (nothing is submitted)  
3. If needed → **Live** with confirm checkbox  
4. **Export .py** — same scenario without UPA  

Files: [`examples/form-workflow.json`](examples/form-workflow.json) · [`examples/params-form.csv`](examples/params-form.csv)

### C) Via API

```http
POST /api/v1/snapshots
{ "url": "https://shop.example.com/catalog" }

POST /api/v1/runs
{ "scenario_id": "<id>", "min_coverage": 0.9 }

POST /api/v1/runs/{run_id}/deliver
{ "kind": "webhook", "target": "https://hooks.example.com/upa" }

POST /api/v1/workflows/recording/start
{ "url": "https://forms.example.com/order", "headed": true }
```

OpenAPI after start: http://127.0.0.1:8000/docs

---

## Quick start

**Windows (recommended):**

```powershell
git clone https://github.com/Vanyc-00X/UPA-Universal-Parser-Automatization-.git
cd UPA-Universal-Parser-Automatization-
.\run.ps1
```

Or double-click [`launch.cmd`](launch.cmd). Desktop shortcut:

```powershell
.\scripts\create-shortcut.ps1
```

| What | URL |
|---|---|
| Web UI | http://127.0.0.1:5173 |
| API | http://127.0.0.1:8000 |
| API docs | http://127.0.0.1:8000/docs |

**Works without AI.** Optional model providers:

| Provider | How |
|---|---|
| **Ollama** | Local default — `.\run.ps1 -PullModel` |
| **llama.cpp** | OpenAI-compatible server at `http://127.0.0.1:8080/v1` |
| **OpenAI / OpenRouter / Grok** | Paste API key on **Dashboard → AI model** (or `.env`) |
| **Custom** | Any `/v1/chat/completions` endpoint |

Settings are saved to `data/llm_settings.json` from the UI. Env vars: see `.env.example`.

**Browser install (mirrors + Chrome/Edge fallback):**

```powershell
.\scripts\install-chromium.ps1
# or
python scripts/install_chromium.py
```

If Playwright Chromium cannot download (CDN / corporate network), UPA automatically tries system **Chrome** or **Edge**. Status: `GET /api/v1/system/browser`.

**Docker (API):**

```powershell
docker compose up --build
```

More detail: [docs/quickstart.md](docs/quickstart.md)

---

## Feature highlights

| Feature | Why it matters |
|---|---|
| Playwright snapshot | DOM, screenshot, network, storage — reproducible base |
| HTML or XHR/JSON source | SPAs often expose the real data in network JSON |
| List → detail | Catalog fields + product-page fields in one run |
| Element map + editor | See what you parse before the first run |
| Scenario versions | Layout change ≠ lost work |
| Coverage report | Spot missing required fields immediately |
| Self-healing | Selector patch proposals, never silent apply |
| Live action recording | Record clicks/fills in a real browser window |
| Workflow + CSV/XLSX | “500 rows — create them on the site” |
| Dry-run / confirm | Fewer accidental submits and payments |
| Change monitoring | Scheduled reruns + diff vs previous run |
| Deliver destinations | Webhook, Google Sheets, PostgreSQL |
| Playwright export | Scenario lives outside UPA |
| Templates | Catalog, form, article — not from zero |

Templates live in the UI (**Templates**) and `GET /api/v1/templates`. Examples in [`examples/`](examples/).

---

## Documentation

| Doc | About |
|---|---|
| [Quick start](docs/quickstart.md) | Install and first scenario |
| [Scenarios & workflows](docs/scenarios.md) | Collection, input, recording, loop/if |
| [Demo](examples/DEMO.md) | Step-by-step “how to use” |
| [FAQ: blocking](docs/faq-blocking.md) | 403, CAPTCHA, robots, healing |
| [Data retention](docs/data-retention.md) | What is stored locally |
| [Disclaimer](docs/disclaimer.md) | ToS and responsibility |
| [PLAN.md](PLAN.md) | Development stages 0–8 |

> Some docs are still in Russian; the product UI and this README are aimed at a global audience.

---

## Stack

`Python` · `FastAPI` · `Playwright` · `SQLite` · `React` · optional `Ollama`

---

## Disclaimer

UPA is for **intentional** automation. Respect site Terms of Service, robots.txt, and the law. Live workflows can submit forms and trigger orders/payments — dangerous steps require confirmation, but you own the run.

Details: [docs/disclaimer.md](docs/disclaimer.md)

---

<p align="center">
  <sub>Built as a local-first alternative to throwaway scrapers.<br>
  If a scenario should outlive one week — you are in the right place.</sub>
</p>
