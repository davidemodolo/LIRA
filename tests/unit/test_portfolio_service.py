"""Unit tests for Portfolio service."""

from decimal import Decimal

from lira.db.models import Holding, Portfolio
from lira.services.portfolio import PortfolioService, TradeResult


def test_create_portfolio(session):
    """Test creating a new portfolio."""
    service = PortfolioService(session)

    portfolio = service.create_portfolio(
        name="My Investment Portfolio",
        description="Long-term investments",
        currency="USD",
    )

    assert portfolio.id is not None
    assert portfolio.name == "My Investment Portfolio"
    assert portfolio.currency == "USD"
    assert portfolio.is_active is True


def test_get_portfolio(session, sample_portfolio):
    """Test getting a portfolio by ID."""
    service = PortfolioService(session)

    found = service.get_portfolio(sample_portfolio.id)

    assert found is not None
    assert found.id == sample_portfolio.id


def test_get_portfolio_not_found(session):
    """Test getting a non-existent portfolio."""
    service = PortfolioService(session)

    found = service.get_portfolio(9999)

    assert found is None


def test_execute_buy_order(session, sample_portfolio):
    """Test executing a buy order."""
    service = PortfolioService(session)

    result = service.execute_buy(
        portfolio_id=sample_portfolio.id,
        symbol="TSLA",
        quantity=Decimal("5"),
        price=Decimal("200.00"),
        fees=Decimal("0"),
    )

    assert result.success is True
    assert result.trade_id is not None
    assert result.holding_id is not None
    assert "TSLA" in result.message


def test_execute_buy_creates_holding(session, sample_portfolio):
    """Test that buy order creates holding if not exists."""
    service = PortfolioService(session)

    result = service.execute_buy(
        portfolio_id=sample_portfolio.id,
        symbol="GOOGL",
        quantity=Decimal("2"),
        price=Decimal("150.00"),
    )

    assert result.success is True

    holding = (
        session.query(Holding)
        .filter_by(
            portfolio_id=sample_portfolio.id,
            symbol="GOOGL",
        )
        .first()
    )

    assert holding is not None
    assert holding.quantity == Decimal("2")


def test_execute_buy_updates_existing_holding(session, sample_portfolio):
    """Test that buy order updates existing holding."""
    service = PortfolioService(session)

    service.execute_buy(
        portfolio_id=sample_portfolio.id,
        symbol="MSFT",
        quantity=Decimal("10"),
        price=Decimal("100.00"),
    )

    result = service.execute_buy(
        portfolio_id=sample_portfolio.id,
        symbol="MSFT",
        quantity=Decimal("5"),
        price=Decimal("110.00"),
    )

    assert result.success is True

    holding = (
        session.query(Holding)
        .filter_by(
            portfolio_id=sample_portfolio.id,
            symbol="MSFT",
        )
        .first()
    )

    assert holding.quantity == Decimal("15")
    assert holding.average_cost == Decimal("103.33")


def test_execute_sell_order(session, sample_portfolio, sample_holding):
    """Test executing a sell order."""
    service = PortfolioService(session)

    result = service.execute_sell(
        portfolio_id=sample_portfolio.id,
        symbol="AAPL",
        quantity=Decimal("5"),
        price=Decimal("180.00"),
    )

    assert result.success is True
    assert result.trade_id is not None
    assert "AAPL" in result.message


def test_execute_sell_insufficient_shares(session, sample_portfolio, sample_holding):
    """Test selling more shares than owned."""
    service = PortfolioService(session)

    result = service.execute_sell(
        portfolio_id=sample_portfolio.id,
        symbol="AAPL",
        quantity=Decimal("100"),
        price=Decimal("180.00"),
    )

    assert result.success is False
    assert "insufficient" in result.error.lower()


def test_execute_sell_no_position(session, sample_portfolio):
    """Test selling a stock not in portfolio."""
    service = PortfolioService(session)

    result = service.execute_sell(
        portfolio_id=sample_portfolio.id,
        symbol="NOW",
        quantity=Decimal("1"),
        price=Decimal("100.00"),
    )

    assert result.success is False
    assert "no position" in result.error.lower()


def test_update_prices(session, sample_portfolio, sample_holding):
    """Test updating holding prices."""
    service = PortfolioService(session)

    new_prices = {"AAPL": Decimal("200.00")}

    updated = service.update_prices(new_prices)

    assert updated == 1

    holding = session.query(Holding).filter_by(symbol="AAPL").first()
    assert holding.current_price == Decimal("200.00")


def test_get_summary(session, sample_portfolio, sample_holding):
    """Test getting portfolio summary."""
    service = PortfolioService(session)

    summary = service.get_summary(sample_portfolio.id)

    assert summary is not None
    assert summary.holdings_count == 1
    assert summary.total_value == Decimal("1750.00")
    assert summary.total_cost == Decimal("1500.00")
    assert summary.total_gain_loss == Decimal("250.00")
