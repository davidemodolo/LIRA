"""Startup initialization for L.I.R.A.

Handles first-run setup including currency, payment methods, and default categories.
"""

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from lira.db.models import Account, AccountType, Category, PaymentMethod, Settings
from lira.db.session import DatabaseSession, init_database

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: list[tuple[str, str | None]] = [
    ("HOUSE", None),
    ("rent", "HOUSE"),
    ("bills", "HOUSE"),
    ("home-stuff", "HOUSE"),
    ("phone", "HOUSE"),
    ("RIDES", None),
    ("fuel", "RIDES"),
    ("car", "RIDES"),
    ("transport", "RIDES"),
    ("HEALTH", None),
    ("meds", "HEALTH"),
    ("sport", "HEALTH"),
    ("visits", "HEALTH"),
    ("barber", "HEALTH"),
    ("WORK", None),
    ("workservices", "WORK"),
    ("workfood", "WORK"),
    ("MISC.", None),
    ("events-culture", "MISC."),
    ("personalcare", "MISC."),
    ("subscriptions", "MISC."),
    ("gifts", "MISC."),
    ("gadgets", "MISC."),
    ("travel", "MISC."),
    ("other", "MISC."),
    ("tax-fees", "MISC."),
    ("FOOD", None),
    ("bar-restaurant", "FOOD"),
    ("groceries", "FOOD"),
    ("HOBBY", None),
    ("books-comics", "HOBBY"),
    ("tradingcards", "HOBBY"),
    ("videogames", "HOBBY"),
    ("rnd-hobby", "HOBBY"),
]

CURRENCY_KEY = "currency"
DEFAULT_CURRENCY = "USD"


def check_initialization_needed() -> dict[str, Any]:
    """Check what needs to be initialized.

    Returns:
        Dict with flags for currency, payment_methods, categories, accounts
    """
    init_database()

    with DatabaseSession() as session:
        currency = session.execute(
            select(Settings).where(Settings.key == CURRENCY_KEY)
        ).scalar_one_or_none()

        payment_methods = session.execute(select(PaymentMethod)).scalars().all()
        categories = session.execute(select(Category)).scalars().all()
        accounts = session.execute(select(Account)).scalars().all()

    return {
        "currency_needed": currency is None,
        "payment_methods_needed": len(payment_methods) == 0,
        "categories_needed": len(categories) == 0,
        "accounts_needed": len(accounts) == 0,
    }


def initialize_default_categories() -> None:
    """Initialize default category hierarchy."""
    init_database()

    with DatabaseSession() as session:
        existing = session.execute(select(Category)).scalars().all()
        if existing:
            logger.info("Categories already exist, skipping initialization")
            return

        name_to_id: dict[str, int] = {}

        for name, parent_name in DEFAULT_CATEGORIES:
            parent_id = name_to_id.get(parent_name) if parent_name else None

            category = Category(
                name=name,
                parent_id=parent_id,
                is_system=True,
            )
            session.add(category)
            session.flush()
            name_to_id[name] = category.id
            logger.info(f"Created category: {name} (parent: {parent_name})")

        logger.info("Default categories initialized")


def get_currency() -> str:
    """Get the configured currency.

    Returns:
        Currency code (e.g., "USD", "EUR")
    """
    init_database()

    with DatabaseSession() as session:
        setting = session.execute(
            select(Settings).where(Settings.key == CURRENCY_KEY)
        ).scalar_one_or_none()

        return setting.value if setting and setting.value else DEFAULT_CURRENCY


def set_currency(currency: str) -> None:
    """Set the currency.

    Args:
        currency: Currency code (e.g., "USD", "EUR")
    """
    init_database()

    with DatabaseSession() as session:
        setting = session.execute(
            select(Settings).where(Settings.key == CURRENCY_KEY)
        ).scalar_one_or_none()

        if setting:
            setting.value = currency
        else:
            setting = Settings(key=CURRENCY_KEY, value=currency)
            session.add(setting)

        logger.info(f"Currency set to: {currency}")


def get_payment_methods() -> list[PaymentMethod]:
    """Get all payment methods.

    Returns:
        List of payment methods
    """
    init_database()

    with DatabaseSession() as session:
        return list(session.execute(select(PaymentMethod)).scalars().all())


def get_payment_method_balance(payment_method_name: str) -> float:
    """Get the balance of a specific payment method.

    Args:
        payment_method_name: Name of the payment method

    Returns:
        Balance as float
    """
    init_database()

    with DatabaseSession() as session:
        pm = session.execute(
            select(PaymentMethod).where(PaymentMethod.name == payment_method_name)
        ).scalar_one_or_none()

        if pm:
            return float(pm.balance)
        return 0.0


def update_payment_method_balance(payment_method_name: str, new_balance: float) -> dict[str, Any]:
    """Set the balance of a payment method directly.

    Args:
        payment_method_name: Name of the payment method
        new_balance: New balance value

    Returns:
        Dict with success status and new balance
    """
    init_database()

    with DatabaseSession() as session:
        pm = session.execute(
            select(PaymentMethod).where(PaymentMethod.name == payment_method_name)
        ).scalar_one_or_none()

        if not pm:
            raise ValueError(f"Payment method '{payment_method_name}' not found")

        old_balance = pm.balance
        pm.balance = Decimal(str(new_balance))

        logger.info(f"Updated balance for {payment_method_name}: {old_balance} -> {new_balance}")

        return {
            "success": True,
            "payment_method": pm.name,
            "old_balance": float(old_balance),
            "new_balance": new_balance,
        }


def transfer_between_payment_methods(
    from_method: str, to_method: str, amount: float
) -> dict[str, Any]:
    """Transfer money between payment methods.

    Args:
        from_method: Source payment method name
        to_method: Destination payment method name
        amount: Amount to transfer

    Returns:
        Dict with success status and transfer details
    """
    init_database()

    with DatabaseSession() as session:
        from_pm = session.execute(
            select(PaymentMethod).where(PaymentMethod.name == from_method)
        ).scalar_one_or_none()

        to_pm = session.execute(
            select(PaymentMethod).where(PaymentMethod.name == to_method)
        ).scalar_one_or_none()

        if not from_pm:
            raise ValueError(f"Payment method '{from_method}' not found")
        if not to_pm:
            raise ValueError(f"Payment method '{to_method}' not found")

        if from_pm.balance < Decimal(str(amount)):
            raise ValueError(f"Insufficient balance in {from_method}. Available: {from_pm.balance}")

        from_pm.balance -= Decimal(str(amount))
        to_pm.balance += Decimal(str(amount))

        logger.info(f"Transferred {amount} from {from_method} to {to_method}")

        return {
            "success": True,
            "from": from_method,
            "to": to_method,
            "amount": amount,
            "from_balance": float(from_pm.balance),
            "to_balance": float(to_pm.balance),
        }


def gain_loss_payment_method(payment_method_name: str, amount: float) -> dict[str, Any]:
    """Record a gain or loss for a payment method.

    Args:
        payment_method_name: Name of the payment method
        amount: Positive for gain, negative for loss

    Returns:
        Dict with success status and new balance
    """
    init_database()

    with DatabaseSession() as session:
        pm = session.execute(
            select(PaymentMethod).where(PaymentMethod.name == payment_method_name)
        ).scalar_one_or_none()

        if not pm:
            raise ValueError(f"Payment method '{payment_method_name}' not found")

        old_balance = pm.balance
        pm.balance += Decimal(str(amount))

        logger.info(
            f"Gain/loss for {payment_method_name}: {amount}. Balance: {old_balance} -> {pm.balance}"
        )

        return {
            "success": True,
            "payment_method": payment_method_name,
            "amount": amount,
            "old_balance": float(old_balance),
            "new_balance": float(pm.balance),
        }


def initialize_first_run(currency: str, payment_methods: list[tuple[str, float]]) -> None:
    """Initialize all first-run settings.

    Args:
        currency: Currency code
        payment_methods: List of (name, balance) tuples
    """
    create_default_account()
    set_currency(currency)

    for i, (pm_name, balance) in enumerate(payment_methods):
        create_payment_method(pm_name, is_default=(i == 0), balance=balance)

    initialize_default_categories()

    logger.info("First-run initialization complete")


def create_default_account() -> Account:
    """Create a default Personal account if none exists."""
    init_database()

    with DatabaseSession() as session:
        existing = session.execute(select(Account)).scalars().first()
        if existing:
            return existing

        account = Account(
            name="Personal",
            account_type=AccountType.CHECKING,
            balance=Decimal("0"),
        )
        session.add(account)
        session.flush()
        logger.info("Created default Personal account")
        return account


def create_payment_method(
    name: str, is_default: bool = False, balance: float = 0.0, account_id: int | None = None
) -> PaymentMethod:
    """Create a new payment method.

    Args:
        name: Payment method name
        is_default: Whether this is the default payment method
        balance: Initial balance for this payment method
        account_id: Optional linked account ID

    Returns:
        Created payment method
    """
    from lira.db.models import Account, AccountType

    init_database()

    with DatabaseSession() as session:
        existing = session.execute(
            select(PaymentMethod).where(PaymentMethod.name == name)
        ).scalar_one_or_none()

        if existing:
            return existing

        personal_account = session.execute(
            select(Account).where(Account.name == "Personal")
        ).scalar_one_or_none()

        if not personal_account:
            personal_account = Account(
                name="Personal",
                account_type=AccountType.CHECKING,
                balance=Decimal("0"),
            )
            session.add(personal_account)
            session.flush()
            logger.info("Created default Personal account")

        if is_default:
            default_pms = (
                session.execute(select(PaymentMethod).where(PaymentMethod.is_default == True))
                .scalars()
                .all()
            )
            for pm in default_pms:
                pm.is_default = False

        payment_method = PaymentMethod(
            name=name,
            is_default=is_default,
            balance=Decimal(str(balance)),
            account_id=account_id or personal_account.id,
        )
        session.add(payment_method)
        session.flush()

        logger.info(f"Created payment method: {name} with balance {balance}")
        return payment_method


def get_categories() -> list[Category]:
    """Get all categories.

    Returns:
        List of categories
    """
    init_database()

    with DatabaseSession() as session:
        return list(session.execute(select(Category)).scalars().all())


def get_category_by_name(name: str) -> Category | None:
    """Get a category by name.

    Args:
        name: Category name

    Returns:
        Category if found
    """
    init_database()

    with DatabaseSession() as session:
        return session.execute(select(Category).where(Category.name == name)).scalar_one_or_none()


def get_category_tree() -> dict[str, dict[str, Any]]:
    """Get category tree for LLM context.

    Returns:
        Dict mapping parent category to list of subcategories
    """
    init_database()

    with DatabaseSession() as session:
        categories = session.execute(select(Category)).scalars().all()

    tree: dict[str, dict[str, Any]] = {}
    for cat in categories:
        if cat.parent_id is None:
            tree[cat.name] = {"id": cat.id, "subcategories": []}
        else:
            parent = next((c for c in categories if c.id == cat.parent_id), None)
            if parent and parent.name in tree:
                tree[parent.name]["subcategories"].append({"id": cat.id, "name": cat.name})

    return tree


def create_persistent_plot(
    name: str,
    plot_type: str = "bar",
    title: str = "",
    x_key: str = "x",
    y_key: str = "y",
) -> dict[str, Any]:
    """Create a persistent plot configuration.

    Args:
        name: Name/title for the plot
        plot_type: Type of plot (bar, line, pie, scatter)
        title: Display title
        x_key: X-axis key
        y_key: Y-axis key

    Returns:
        Dict with success status and plot details
    """
    from lira.db.models import DashboardPlot

    init_database()

    with DatabaseSession() as session:
        plot = DashboardPlot(
            name=name,
            plot_type=plot_type,
            title=title or name,
            x_key=x_key,
            y_key=y_key,
        )
        session.add(plot)
        session.commit()
        session.refresh(plot)

        logger.info(f"Created persistent plot: {name}")
        return {
            "success": True,
            "id": plot.id,
            "name": plot.name,
            "plot_type": plot.plot_type,
            "title": plot.title,
        }
