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


@dataclass(frozen=True)
class CryptoInvoiceResult:
    invoice_id: str
    invoice_url: str


@dataclass(frozen=True)
class CryptoInvoiceStatusResult:
    invoice_id: str
    status: str


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

    async def get_available_balance(self, *, asset_code: str = "USDT") -> Decimal:
        """Возвращает доступный баланс по активу (без onhold)."""

        balances = await self.get_balance()
        target = asset_code.strip().upper()
        for item in balances:
            code = str(getattr(item, "currency_code", "")).upper()
            if code != target:
                continue
            available = getattr(item, "available", 0)
            return Decimal(str(available))
        return Decimal("0")

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
            error_str = str(e).upper()
            logger.exception("CryptoPay API error: %s", e)
            
            # Специальная обработка NOT_ENOUGH_COINS
            if "NOT_ENOUGH_COINS" in error_str or "INSUFFICIENT" in error_str:
                raise RuntimeError(
                    f"❌ NOT_ENOUGH_COINS: На счёте CryptoBot недостаточно средств {amount} {asset.value}. "
                    f"Пополните баланс и попробуйте снова."
                ) from e
            
            await alert_cryptobot_error(str(e))
            raise RuntimeError(f"CryptoPay error: {e}") from e

        return CryptoCheckResult(
            check_id=str(check.check_id),
            check_url=check.bot_check_url,
        )

    async def create_topup_invoice(
        self,
        amount: Decimal,
        *,
        description: str = "Top up app balance",
    ) -> CryptoInvoiceResult:
        """Создаёт invoice на пополнение баланса приложения (оплата самим админом)."""

        if amount <= 0:
            raise ValueError("Amount must be > 0")

        client = self._get_client()
        settings = get_settings()
        asset = _asset_from_settings(settings.crypto_asset)

        try:
            invoice = await client.create_invoice(
                asset=asset,
                amount=str(amount),
                description=description[:1024],
            )
        except CryptoPayError as exc:
            logger.exception("CryptoPay API error while creating invoice: %s", exc)
            await alert_cryptobot_error(str(exc))
            raise RuntimeError(f"CryptoPay error: {exc}") from exc

        invoice_url = getattr(invoice, "bot_invoice_url", None)
        if not invoice_url:
            raise RuntimeError("CryptoPay invoice URL is missing in response")

        return CryptoInvoiceResult(
            invoice_id=str(getattr(invoice, "invoice_id", "")),
            invoice_url=str(invoice_url),
        )

    async def get_invoice_status(self, invoice_id: int) -> CryptoInvoiceStatusResult:
        """Возвращает статус invoice по его ID."""

        if invoice_id <= 0:
            raise ValueError("Invoice ID must be > 0")

        client = self._get_client()
        try:
            invoice = await client.get_invoice(invoice=invoice_id)
        except CryptoPayError as exc:
            logger.exception("CryptoPay API error while fetching invoice status: %s", exc)
            await alert_cryptobot_error(str(exc))
            raise RuntimeError(f"CryptoPay error: {exc}") from exc

        if invoice is None:
            raise RuntimeError(f"Invoice {invoice_id} not found")

        status = str(getattr(invoice, "status", "")).strip().lower()
        return CryptoInvoiceStatusResult(invoice_id=str(invoice_id), status=status)
