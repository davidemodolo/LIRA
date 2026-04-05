# Database Schema

This document describes the L.I.R.A. database schema. The database uses SQLite by default (configurable via `DATABASE_URL` env var).

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ACCOUNTS                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │   CHECKING   │  │   SAVINGS    │  │CREDIT_CARD  │  │ INVESTMENT │  │
│  │  (Personal)  │  │              │  │              │  │            │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘  └──────┬─────┘  │
│         │                   │                                    │        │
│         │    ┌────────────┴────────────┐                      │        │
│         │    │   PAYMENT METHODS       │                      │        │
│         │    │  ┌─────┐ ┌─────┐      │                      │        │
│         │    │  │Cash │ │Revo │      │◄─────────────────────┘        │
│         │    │  │     │ │lut │      │                               │
│         │    │  └─────┘ └─────┘      │                               │
│         │    └───────────────────────┘                               │
│         │                                                               │
│         └───────────────────┬───────────────────────────────────────────┘
│                             │                                           
│         ┌───────────────────┴───────────────────────────────────────────┐
│         │                    TRANSACTIONS                                │
│         │  ┌─────────────────────────────────────────────────────────┐  │
│         │  │ date, amount, description, category, payment_method   │  │
│         │  └─────────────────────────────────────────────────────────┘  │
│         │                                                               │
└─────────┼───────────────────────────────────────────────────────────────┘
          │
          │
┌─────────┴───────────────────────────────────────────────────────────────┐
│                              CATEGORIES                                  │
│                                                                          │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐           │
│  │  HOUSE  │    │  RIDES  │    │  HEALTH │    │   FOOD  │    ...     │
│  │  ├ rent │    │ ├ fuel  │    │ ├ meds  │    │├bar-rest│           │
│  │  │bills │    │ │ car   │    │ │ sport  │    ││groceri │           │
│  │  └──────│    │ └──────│    │ └──────│    │└───────┘           │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           INVESTMENTS                                      │
│                                                                          │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────────────┐  │
│  │ PORTFOLIOS  │────►│  HOLDINGS   │◄────│         TRADES          │  │
│  │ (default)   │     │ AAPL, BTC   │     │  buy/sell records       │  │
│  └─────────────┘     └──────┬──────┘     └───────────┬─────────────┘  │
│                             │                        │                 │
│                      ┌──────┴──────┐          ┌─────┴────────┐      │
│                      │    LOTS     │          │    LOTS      │      │
│                      │ (tax lots)  │◄─────────│   (sales)    │      │
│                      └─────────────┘          └──────────────┘      │
└──────────────────────────────────────────────────────────────────────────┘
```

## Tables

### accounts

Stores financial accounts. Each account can have multiple payment methods and transactions.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | VARCHAR(255) | Account name (e.g., "Personal", "Business") |
| account_type | ENUM | checking, savings, credit_card, investment, cash, loan, mortgage, brokerage, retirement |
| currency | VARCHAR(3) | Currency code (USD, EUR, etc.) |
| balance | DECIMAL(19,4) | Current balance |
| institution | VARCHAR(255) | Bank/institution name |
| account_number | VARCHAR(50) | Masked account number |
| is_active | BOOLEAN | Whether account is active |
| notes | TEXT | User notes |
| metadata_json | TEXT | Additional JSON metadata |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update timestamp |

### payment_methods

User-defined payment methods linked to accounts. Used to track spending by payment type.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | VARCHAR(100) UNIQUE | Payment method name (Cash, Debit Card, etc.) |
| balance | DECIMAL(19,4) | Current balance in this method |
| account_id | INTEGER FK | Link to accounts table |
| is_default | BOOLEAN | Default payment method |
| created_at | DATETIME | Creation timestamp |

### transactions

Individual financial transactions. Can be linked to accounts and payment methods.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| account_id | INTEGER FK | Link to accounts |
| category_id | INTEGER FK | Link to categories |
| payment_method_id | INTEGER FK | Link to payment_methods |
| transaction_type | ENUM | income, expense, transfer, dividend, buy, sell, fee, interest |
| amount | DECIMAL(19,4) | Transaction amount |
| currency | VARCHAR(3) | Currency code |
| description | VARCHAR(500) | Transaction description |
| merchant | VARCHAR(255) | Merchant name |
| date | DATETIME | Transaction date (indexed) |
| is_reconciled | BOOLEAN | Whether verified |
| notes | TEXT | User notes |
| tags | VARCHAR(500) | Comma-separated tags |
| metadata_json | TEXT | Additional JSON metadata |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update timestamp |

### categories

Hierarchical transaction categories. Supports parent-child relationships for subcategories.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | VARCHAR(100) UNIQUE | Category name |
| parent_id | INTEGER FK | Self-reference to parent category |
| icon | VARCHAR(50) | Icon name |
| color | VARCHAR(7) | Hex color code |
| is_system | BOOLEAN | System-managed category |
| created_at | DATETIME | Creation timestamp |

### portfolios

Investment portfolio containers.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | VARCHAR(255) | Portfolio name |
| description | TEXT | Description |
| currency | VARCHAR(3) | Base currency |
| is_active | BOOLEAN | Active status |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update |

### holdings

Current security positions within a portfolio.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| portfolio_id | INTEGER FK | Link to portfolios |
| symbol | VARCHAR(20) | Ticker symbol |
| name | VARCHAR(255) | Security name |
| quantity | DECIMAL(19,8) | Number of shares/units |
| average_cost | DECIMAL(19,4) | Average cost basis |
| current_price | DECIMAL(19,4) | Current market price |
| last_updated | DATETIME | Last price update |
| notes | TEXT | User notes |
| created_at | DATETIME | Creation timestamp |
| updated_at | DATETIME | Last update |

### trades

Individual trade execution records.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| portfolio_id | INTEGER FK | Link to portfolios |
| holding_id | INTEGER FK | Link to holdings |
| symbol | VARCHAR(20) | Ticker symbol |
| trade_type | ENUM | Transaction type |
| quantity | DECIMAL(19,8) | Trade quantity |
| price | DECIMAL(19,4) | Trade price |
| fees | DECIMAL(19,4) | Trading fees |
| total | DECIMAL(19,4) | Total value |
| date | DATETIME | Trade date |
| notes | TEXT | User notes |
| created_at | DATETIME | Creation timestamp |

### lots

Tax lots for cost basis tracking (FIFO/LIFO).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| holding_id | INTEGER FK | Link to holdings |
| trade_id | INTEGER FK | Link to trades |
| quantity | DECIMAL(19,8) | Original quantity |
| remaining | DECIMAL(19,8) | Remaining quantity |
| cost_basis | DECIMAL(19,4) | Cost per unit |
| purchase_date | DATETIME | Purchase date |
| created_at | DATETIME | Creation timestamp |

### lot_sales

Records of shares sold from specific lots.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| lot_id | INTEGER FK | Link to lots |
| trade_id | INTEGER FK | Link to trades |
| quantity | DECIMAL(19,8) | Quantity sold |
| proceeds | DECIMAL(19,4) | Sale proceeds |
| cost_basis | DECIMAL(19,4) | Total cost basis |
| gain_loss | DECIMAL(19,4) | Capital gain/loss |
| sale_date | DATETIME | Sale date |
| is_short_term | BOOLEAN | Short-term vs long-term |
| created_at | DATETIME | Creation timestamp |

### settings

Key-value store for user preferences.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| key | VARCHAR(100) UNIQUE | Setting key (e.g., "currency") |
| value | VARCHAR(500) | Setting value |
| updated_at | DATETIME | Last update |

### dashboard_plots

Persistent dashboard plot configurations.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | VARCHAR(255) | Plot name |
| plot_type | VARCHAR(50) | bar, line, pie, scatter |
| title | VARCHAR(255) | Display title |
| x_key | VARCHAR(50) | X-axis data key |
| y_key | VARCHAR(50) | Y-axis data key |
| config_json | TEXT | Additional config |
| created_at | DATETIME | Creation timestamp |

## Design Decisions

### Single User vs Multi-User

The schema is designed for single-user operation initially, but allows for multi-user extension:

1. **No user_id columns** - Currently all data belongs to one user
2. **Future migration path**: Add `user_id` to all tables or create a `users` table and add foreign keys
3. **Authentication**: Can be added at the API layer without schema changes

### Payment Methods vs Accounts

- **Accounts**: Traditional bank accounts (checking, savings, credit cards)
- **Payment Methods**: How user actually pays (Cash, Debit Card, specific credit cards)

Payment methods are linked to accounts but provide more granular tracking. For example:
- Account: "Chase Checking" (balance: $5000)
- Payment Methods: "Cash" ($200), "Debit Card" ($4800) - both linked to the same account

### Category Hierarchy

Categories use self-referential foreign keys for parent-child relationships. This allows:
- Unlimited depth nesting
- Efficient queries with recursive CTEs
- Natural grouping (FOOD > restaurant, groceries)

### Investment Tracking

The schema supports:
- Multiple portfolios
- Lot-based cost basis tracking
- FIFO/LIFO tax calculations
- Realized gain/loss tracking

## Default Data

On first run, L.I.R.A. creates:
1. Default "Personal" checking account
2. Currency setting (prompted from user)
3. Payment methods with initial balances (prompted from user)
4. Default category hierarchy:

```
HOUSE: rent, bills, home-stuff, phone
RIDES: fuel, car, transport
HEALTH: meds, sport, visits, barber
WORK: workservices, workfood
MISC.: events-culture, personalcare, subscriptions, gifts, gadgets, travel, other, tax-fees
FOOD: bar-restaurant, groceries
HOBBY: books-comics, tradingcards, videogames, rnd-hobby
```

## Indexes

Key indexes for query performance:
- `transactions(date, transaction_type)` - Date-based queries
- `transactions(account_id, date)` - Account history
- `transactions(category_id)` - Category filtering
- `holdings(symbol)` - Security lookups
- `trades(symbol, date)` - Trade history
