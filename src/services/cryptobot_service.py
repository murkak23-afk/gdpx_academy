from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from aiosend import CryptoPay
from aiosend.enums import Asset
from aiosend.exceptions import CryptoPayError

from src.core.config import get_settings
from src.services.alert_service import alert_cryptobot_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CryptoCheckResult:
    check_id: str
    check_url: str


def _asset_from_settings(raw: str | None) -> Asset:
    code = (raw or "USDT").strip().upper()
    try:
        return Asset[code]
    except KeyError:
        logger.warning("Unknown asset %s → fallback USDT", raw)
        return Asset.USDT


class CryptoBotService:
    def __init__(self) -> None:
        self._client: CryptoPay | None = None

    def _get_client(self) -> CryptoPay:
        if self._client is None:
            settings = get_settings()

            if not settings.crypto_pay_token:
                raise RuntimeError("CRYPTO_PAY_TOKEN not set")

            logger.info("CryptoBot init (token prefix=%s)", settings.crypto_pay_token[:5])

            self._client = CryptoPay(settings.crypto_pay_token)

        return self._client

    async def get_balance(self):
        client = self._get_client()
        return await client.get_balance()

    async def create_usdt_check(self, amount: Decimal, comment: str = "") -> CryptoCheckResult:
        """Создаёт чек в активе из настроек (по умолчанию USDT). Alias для `create_check`."""

        return await self.create_check(amount=amount, comment=comment)

    async def create_check(
        self,
        amount: Decimal,
        comment: str = "",
    ) -> CryptoCheckResult:
        if amount <= 0:
            raise ValueError("Amount must be > 0")

        client = self._get_client()
        settings = get_settings()
        asset = _asset_from_settings(settings.crypto_asset)

        logger.info("Create check: %s %s", amount, asset.value)

        try:
            check = await client.create_check(
                amount=str(amount),  # ✅ важно!
                asset=asset,
            )

        except CryptoPayError as e:
            logger.exception("CryptoPay API error: %s", e)
            await alert_cryptobot_error(str(e))
            raise RuntimeError(f"CryptoPay error: {e}") from e

        return CryptoCheckResult(
            check_id=str(check.check_id),
            check_url=check.bot_check_url,
        )
