from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from src.core.config import get_settings
from src.domain.finance.cryptobot_service import CryptoBotService, CryptoCheckResult

logger = logging.getLogger(__name__)


class InsufficientBalanceError(Exception):
    """Недостаточно средств на балансе Crypto Bot для создания чека."""


class WithdrawalService:
    """Оркестрация вывода: проверка баланса по активу из настроек и создание чека Crypto Pay."""

    def __init__(self, crypto: CryptoBotService | None = None) -> None:
        self._crypto = crypto or CryptoBotService()

    @staticmethod
    def _currency_code_str(currency_code: object) -> str:
        if hasattr(currency_code, "value"):
            return str(currency_code.value).strip().upper()
        return str(currency_code).strip().upper()

    async def available_amount(self) -> Decimal:
        """Доступный баланс по `CRYPTO_ASSET` из настроек."""

        want = (get_settings().crypto_asset or "USDT").strip().upper()
        balances = await self._crypto.get_balance()
        for row in balances:
            if self._currency_code_str(row.currency_code) == want:
                return Decimal(str(row.available))
        logger.warning("Баланс для актива %s не найден в ответе getBalance", want)
        return Decimal("0")

    async def create_pending_request(self, amount: Decimal) -> str:
        """Заготовка под запись заявки в БД; сейчас только лог и стабильный id."""

        if amount <= 0:
            raise ValueError("Сумма должна быть > 0")
        request_id = uuid.uuid4().hex[:16]
        logger.info("Заявка на вывод (pending): id=%s amount=%s", request_id, amount)
        return request_id

    async def execute_withdrawal(
        self,
        amount: Decimal,
        *,
        comment: str = "",
    ) -> CryptoCheckResult:
        """Проверяет баланс и создаёт чек на вывод."""

        if amount <= 0:
            raise ValueError("Сумма должна быть > 0")

        available = await self.available_amount()
        if available < amount:
            raise InsufficientBalanceError(f"Недостаточно средств: доступно {available}, запрошено {amount}")

        return await self._crypto.create_check(amount, comment=comment)
