"""Portfolio management service.

Handles investment portfolio operations including:
- Buying and selling securities
- Cost basis tracking
- Performance calculations
- Tax lot management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from lira.db.models import (
    Holding,
    Lot,
    LotSale,
    Portfolio,
    Trade,
    TransactionType,
)

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    """Result of a trade execution."""

    success: bool
    trade_id: int | None = None
    holding_id: int | None = None
    message: str = ""
    error: str | None = None


@dataclass
class PortfolioSummary:
    """Portfolio summary data."""

    total_value: Decimal
    total_cost: Decimal
    total_gain_loss: Decimal
    total_gain_loss_percent: Decimal
    holdings_count: int
    cash_available: Decimal


class PortfolioService:
    """Service for managing investment portfolios."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_portfolio(
        self,
        name: str,
        description: str | None = None,
        currency: str = "USD",
    ) -> Portfolio:
        """Create a new portfolio.

        Args:
            name: Portfolio name
            description: Optional description
            currency: Base currency

        Returns:
            Created portfolio
        """
        portfolio = Portfolio(
            name=name,
            description=description,
            currency=currency,
        )
        self.session.add(portfolio)
        self.session.commit()

        logger.info("Created portfolio: %s (ID: %d)", name, portfolio.id)
        return portfolio

    def get_portfolio(self, portfolio_id: int) -> Portfolio | None:
        """Get portfolio by ID.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            Portfolio or None
        """
        return self.session.query(Portfolio).filter_by(id=portfolio_id).first()

    def execute_buy(
        self,
        portfolio_id: int,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fees: Decimal = Decimal("0"),
        notes: str | None = None,
    ) -> TradeResult:
        """Execute a buy order.

        Args:
            portfolio_id: Portfolio ID
            symbol: Stock symbol
            quantity: Number of shares
            price: Price per share
            fees: Transaction fees
            notes: Optional notes

        Returns:
            TradeResult with execution outcome
        """
        try:
            portfolio = self.get_portfolio(portfolio_id)
            if not portfolio:
                return TradeResult(success=False, error="Portfolio not found")

            holding = (
                self.session.query(Holding)
                .filter_by(
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                )
                .first()
            )

            total_cost = quantity * price + fees

            if holding:
                new_quantity = holding.quantity + quantity
                new_avg_cost = (
                    (holding.quantity * holding.average_cost) + (quantity * price)
                ) / new_quantity
                holding.quantity = new_quantity
                holding.average_cost = new_avg_cost
            else:
                holding = Holding(
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                    quantity=quantity,
                    average_cost=price,
                    current_price=price,
                )
                self.session.add(holding)

            trade = Trade(
                portfolio_id=portfolio_id,
                holding_id=holding.id,
                symbol=symbol,
                trade_type=TransactionType.BUY,
                quantity=quantity,
                price=price,
                fees=fees,
                total=total_cost,
                date=datetime.utcnow(),
                notes=notes,
            )
            self.session.add(trade)

            lot = Lot(
                holding_id=holding.id,
                trade_id=trade.id,
                quantity=quantity,
                remaining=quantity,
                cost_basis=total_cost,
                purchase_date=datetime.utcnow(),
            )
            self.session.add(lot)

            self.session.commit()

            logger.info(
                "Executed BUY: %s %s @ $%s",
                quantity,
                symbol,
                price,
            )

            return TradeResult(
                success=True,
                trade_id=trade.id,
                holding_id=holding.id,
                message=f"Bought {quantity} shares of {symbol} at ${price}",
            )

        except Exception as e:
            self.session.rollback()
            logger.exception("Buy order failed")
            return TradeResult(success=False, error=str(e))

    def execute_sell(
        self,
        portfolio_id: int,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fees: Decimal = Decimal("0"),
        lot_selection: str = "fifo",
        notes: str | None = None,
    ) -> TradeResult:
        """Execute a sell order.

        Args:
            portfolio_id: Portfolio ID
            symbol: Stock symbol
            quantity: Number of shares
            price: Price per share
            fees: Transaction fees
            lot_selection: Lot selection method (fifo, lifo, specific)
            notes: Optional notes

        Returns:
            TradeResult with execution outcome
        """
        try:
            holding = (
                self.session.query(Holding)
                .filter_by(
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                )
                .first()
            )

            if not holding:
                return TradeResult(success=False, error=f"No position in {symbol}")

            if holding.quantity < quantity:
                return TradeResult(
                    success=False,
                    error=f"Insufficient shares. Have {holding.quantity}, trying to sell {quantity}",
                )

            total_proceeds = quantity * price - fees

            trade = Trade(
                portfolio_id=portfolio_id,
                holding_id=holding.id,
                symbol=symbol,
                trade_type=TransactionType.SELL,
                quantity=quantity,
                price=price,
                fees=fees,
                total=total_proceeds,
                date=datetime.utcnow(),
                notes=notes,
            )
            self.session.add(trade)

            remaining_to_sell = quantity
            lots = (
                self.session.query(Lot)
                .filter_by(
                    holding_id=holding.id,
                )
                .order_by(Lot.purchase_date.asc())
                .all()
            )

            for lot in lots:
                if remaining_to_sell <= 0:
                    break

                sell_from_lot = min(lot.remaining, remaining_to_sell)
                cost_basis_per_share = lot.cost_basis / lot.quantity
                sold_cost_basis = cost_basis_per_share * sell_from_lot

                lot_sale = LotSale(
                    lot_id=lot.id,
                    trade_id=trade.id,
                    quantity=sell_from_lot,
                    proceeds=price * sell_from_lot,
                    cost_basis=sold_cost_basis,
                    gain_loss=(price * sell_from_lot) - sold_cost_basis,
                    sale_date=datetime.utcnow(),
                    is_short_term=((datetime.utcnow() - lot.purchase_date).days < 365),
                )
                self.session.add(lot_sale)

                lot.remaining -= sell_from_lot
                remaining_to_sell -= sell_from_lot

            holding.quantity -= quantity
            if holding.quantity == 0:
                self.session.delete(holding)

            self.session.commit()

            logger.info(
                "Executed SELL: %s %s @ $%s",
                quantity,
                symbol,
                price,
            )

            return TradeResult(
                success=True,
                trade_id=trade.id,
                message=f"Sold {quantity} shares of {symbol} at ${price}",
            )

        except Exception as e:
            self.session.rollback()
            logger.exception("Sell order failed")
            return TradeResult(success=False, error=str(e))

    def update_prices(self, prices: dict[str, Decimal]) -> int:
        """Update current prices for holdings.

        Args:
            prices: Dict mapping symbol to current price

        Returns:
            Number of holdings updated
        """
        updated = 0

        for symbol, price in prices.items():
            holdings = self.session.query(Holding).filter_by(symbol=symbol).all()
            for holding in holdings:
                holding.current_price = price
                holding.last_updated = datetime.utcnow()
                updated += 1

        self.session.commit()
        logger.info("Updated prices for %d holdings", updated)
        return updated

    def get_summary(self, portfolio_id: int) -> PortfolioSummary | None:
        """Get portfolio summary.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            PortfolioSummary or None
        """
        portfolio = self.get_portfolio(portfolio_id)
        if not portfolio:
            return None

        holdings = self.session.query(Holding).filter_by(portfolio_id=portfolio_id).all()

        total_value = Decimal("0")
        total_cost = Decimal("0")

        for h in holdings:
            current = h.current_price or h.average_cost
            total_value += h.quantity * current
            total_cost += h.quantity * h.average_cost

        total_gain_loss = total_value - total_cost
        total_gain_loss_pct = (total_gain_loss / total_cost * 100) if total_cost else Decimal("0")

        return PortfolioSummary(
            total_value=total_value,
            total_cost=total_cost,
            total_gain_loss=total_gain_loss,
            total_gain_loss_percent=total_gain_loss_pct,
            holdings_count=len(holdings),
            cash_available=Decimal("0"),
        )
