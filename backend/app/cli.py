"""Консольный интерфейс UPA: инициализация БД, запуск сервера, диагностика."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app import __version__
from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine
from app.core.logging import configure_logging, get_logger

log = get_logger("upa.cli")


def _cmd_init_db(_args: argparse.Namespace) -> int:
    """Создаёт схему БД и каталоги данных."""
    from app.storage import Base

    settings = get_settings()
    settings.ensure_directories()
    engine = init_engine(settings)

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await dispose_engine()

    asyncio.run(_run())
    print(f"Схема БД готова: {settings.database_path}")
    print(f"Каталог данных: {settings.data_dir}")
    return 0


def _cmd_check(_args: argparse.Namespace) -> int:
    """Проверяет подсистемы и печатает отчёт. Ненулевой код — только при сбое БД."""
    from app.api.deps import check_database, check_llm, python_version

    settings = get_settings()
    settings.ensure_directories()
    init_engine(settings)

    async def _run() -> tuple[str, str | None, dict]:
        db = await check_database(settings)
        llm = await check_llm(settings)
        await dispose_engine()
        return db[0], db[1], llm

    db_status, db_detail, llm = asyncio.run(_run())

    print(f"UPA {__version__}  env={settings.env}  python={python_version()}")
    print(f"  данные:   {settings.data_dir}")
    print(f"  БД:       {'OK' if db_status == 'ok' else 'СБОЙ'}  {settings.database_url}")
    if db_detail:
        print(f"            {db_detail}")
    if llm["available"]:
        print(
            f"  ИИ:       OK  {llm['provider']}:{llm.get('model')} "
            f"(доступно моделей: {len(llm['models'])})"
        )
        if llm.get("detail"):
            print(f"            {llm['detail']}")
    else:
        reason = llm.get("detail") or "недоступна"
        print(f"  ИИ:       НЕДОСТУПЕН ({reason}) — приложение работает без ИИ")
    print("  браузер:  код Этапа 1 готов; для съёмки реальных страниц нужен Chromium")
    return 0 if db_status == "ok" else 1


def _cmd_info(_args: argparse.Namespace) -> int:
    """Печатает действующие настройки (без секретов)."""
    settings = get_settings()
    payload = {
        "app": settings.app_name,
        "version": __version__,
        "env": settings.env,
        "database_url": settings.database_url,
        "database_path": str(settings.database_path) if settings.database_path else None,
        "data_dir": str(settings.data_dir),
        "cors_origins": settings.cors_origins,
        "browser": {
            "headless": settings.browser_headless,
            "timeout_ms": settings.browser_timeout_ms,
            "locale": settings.browser_locale,
            "dom_max_tokens": settings.dom_max_tokens,
        },
        "llm": {
            "provider": settings.llm_provider,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "cloud_fallback": settings.llm_cloud_fallback,
            "cloud_api_key_set": bool(settings.llm_cloud_api_key),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Запускает uvicorn с настройками приложения."""
    import uvicorn

    settings = get_settings()
    configure_logging(settings)
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upa", description="UPA — служебные команды")
    parser.add_argument("--version", action="version", version=f"UPA {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="создать схему базы данных")
    p_init.set_defaults(func=_cmd_init_db)

    p_check = sub.add_parser("check", help="проверить подсистемы (БД, ИИ)")
    p_check.set_defaults(func=_cmd_check)

    p_info = sub.add_parser("info", help="показать действующие настройки")
    p_info.set_defaults(func=_cmd_info)

    p_serve = sub.add_parser("serve", help="запустить HTTP API")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true", help="автоперезапуск при изменениях")
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings())
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
        return 130


if __name__ == "__main__":
    sys.exit(main())
