from src.database.models.enums import PayoutStatus, UserRole


def test_payout_status_values() -> None:
    assert PayoutStatus.PENDING.value == "pending"
    assert PayoutStatus.PAID.value == "paid"
    assert PayoutStatus.CANCELLED.value == "cancelled"


def test_user_role_includes_chief_admin() -> None:
    assert UserRole.CHIEF_ADMIN.value == "chief_admin"


def test_user_role_includes_admin() -> None:
    assert UserRole.ADMIN.value == "admin"
