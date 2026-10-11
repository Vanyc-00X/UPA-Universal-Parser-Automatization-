"""Проверка robots.txt с явным переключателем ответственности."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import Settings


@dataclass
class RobotsCheck:
    """Результат проверки robots.txt."""

    url: str
    allowed: bool
    fetched: bool
    robots_url: str
    detail: str
    user_agent: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "allowed": self.allowed,
            "fetched": self.fetched,
            "robots_url": self.robots_url,
            "detail": self.detail,
            "user_agent": self.user_agent,
        }


async def check_robots(settings: Settings, url: str) -> RobotsCheck:
    """Проверяет, разрешает ли robots.txt обход указанного адреса.

    Если ``respect_robots_txt`` выключен — всегда ``allowed=True``, но с пометкой,
    что ответственность на пользователе.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{origin}/robots.txt"
    user_agent = settings.browser_user_agent or "UPABot"

    if not settings.respect_robots_txt:
        return RobotsCheck(
            url=url,
            allowed=True,
            fetched=False,
            robots_url=robots_url,
            detail="проверка robots.txt отключена: ответственность на пользователе",
            user_agent=user_agent,
        )

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(robots_url, headers={"User-Agent": user_agent})
        if response.status_code >= 400:
            return RobotsCheck(
                url=url,
                allowed=True,
                fetched=False,
                robots_url=robots_url,
                detail=(
                    f"robots.txt недоступен (HTTP {response.status_code}) "
                    "— обход не запрещён явно"
                ),
                user_agent=user_agent,
            )
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        allowed = parser.can_fetch(user_agent, url)
        return RobotsCheck(
            url=url,
            allowed=allowed,
            fetched=True,
            robots_url=robots_url,
            detail="разрешено robots.txt" if allowed else "запрещено robots.txt для этого пути",
            user_agent=user_agent,
        )
    except Exception as exc:  # noqa: BLE001 — сеть/разбор
        return RobotsCheck(
            url=url,
            allowed=True,
            fetched=False,
            robots_url=robots_url,
            detail=f"не удалось проверить robots.txt: {type(exc).__name__}: {exc}",
            user_agent=user_agent,
        )
