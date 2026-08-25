from urllib.parse import quote

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession


def create_telegram_bot(
    *,
    token: str,
    socks5_proxy_enabled: bool,
    socks5_proxy_host: str | None,
    socks5_proxy_port: int | None,
    socks5_proxy_username: str | None,
    socks5_proxy_password: str | None,
) -> Bot:
    if not socks5_proxy_enabled:
        return Bot(token=token)
    username = quote(socks5_proxy_username or "", safe="")
    password = quote(socks5_proxy_password or "", safe="")
    session = AiohttpSession(
        proxy=(f"socks5://{username}:{password}@{socks5_proxy_host}:{socks5_proxy_port}")
    )
    return Bot(token=token, session=session)
