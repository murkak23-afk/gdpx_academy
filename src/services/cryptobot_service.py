"""Интеграция с Crypto Pay API (@CryptoBot) для создания чеков на выплату."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from aiosend import CryptoPay
from aiosend.enums import Asset
from aiosend.exceptions import CryptoPayError

from src.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CryptoCheckResult:
    """Результат создания чека для сохранения в БД и UI."""

    check_id: str
    check_url: str


def _asset_from_settings(raw: str | None) -> Asset:
    code = (raw or "USDT").strip().upper()
    try:
        return Asset[code]
    except KeyError:
        logger.warning("Неизвестный CRYPTO_ASSET=%s, используется USDT", raw)
        return Asset.USDT


class CryptoBotService:
    """Обёртка над aiosend.CryptoPay: токен из окружения, без секретов в коде."""

    def __init__(self, token: str | None = None) -> None:
        self._override_token = token
        self._client: CryptoPay | None = None

    def _resolve_token(self) -> str:
        token = self._override_token if self._override_token is not None else get_settings().crypto_pay_token
        if not token:
            msg = "CRYPTO_PAY_TOKEN не задан. Укажите токен Crypto Pay в .env для выплат через чек."
            raise RuntimeError(msg)
        return token

    def _get_client(self) -> CryptoPay:
        if self._client is None:
            self._client = CryptoPay(self._resolve_token())
        return self._client

    async def create_usdt_check(self, *, amount: Decimal, comment: str) -> CryptoCheckResult:
        """Создаёт чек в Crypto Pay. `comment` в API не передаётся — только для логов."""

        if amount <= 0:
            raise RuntimeError("Сумма чека должна быть больше нуля")

        settings = get_settings()
        asset = _asset_from_settings(settings.crypto_asset)
        client = self._get_client()

        logger.info(
            "CryptoBot create_check: amount=%s asset=%s comment=%s",
            amount,
            asset.value,
            comment[:200] if comment else "",
        )

        try:
            check = await client.create_check(amount=float(amount), asset=asset)
        except CryptoPayError as exc:
            logger.exception("Ошибка Crypto Pay API при create_check")
            raise RuntimeError(str(exc)) from exc

        return CryptoCheckResult(
            check_id=str(check.check_id),
            check_url=check.bot_check_url,
        )
