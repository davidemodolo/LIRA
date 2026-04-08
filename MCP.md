# MCP Reference

All tools and prompts exposed by the L.I.R.A. MCP server.

---

## Tools

### Accounts

#### `list_accounts`
List all user accounts with balances and metadata.

| Argument | Type | Default | Description |
|---|---|---|---|
| `active_only` | `bool` | `true` | If true, only returns active accounts |

#### `create_account`
Create a new financial account (checking, savings, credit, loan).

| Argument | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *required* | Display name (e.g. "Chase Checking") |
| `account_type` | `str` | `"checking"` | Type: "checking", "savings", etc. |
| `balance` | `float` | `0.0` | Initial starting balance |

---

### Transactions

#### `create_transaction`
Log an income, expense, or transfer against an account. Automatically updates account and payment method balances.

| Argument | Type | Default | Description |
|---|---|---|---|
| `account_id` | `int` | *required* | Account ID (use `list_accounts`) |
| `amount` | `float` | *required* | Monetary value (always positive) |
| `transaction_type` | `str` | *required* | `"expense"`, `"income"`, or `"transfer"` |
| `description` | `str` | *required* | Short memo |
| `merchant` | `str` | *required* | Merchant or payee name |
| `category_id` | `int` | `null` | Primary category ID |
| `category_name` | `str` | `null` | Primary category name (e.g. "FOOD > groceries"). Resolves to ID |
| `secondary_category_id` | `int` | `null` | Secondary category ID |
| `secondary_category_name` | `str` | `null` | Secondary category name. Resolves to ID |
| `payment_method_id` | `int` | `null` | Payment method ID |
| `payment_method_name` | `str` | `null` | Payment method name (e.g. "Cash"). Resolves to ID |
| `date` | `str` | now | ISO format date (YYYY-MM-DD) |

#### `get_transactions`
Query transactions with filters.

| Argument | Type | Default | Description |
|---|---|---|---|
| `account_id` | `int` | `null` | Filter by account |
| `category` | `str` | `null` | Filter by category name (partial match) |
| `start_date` | `str` | `null` | On or after (YYYY-MM-DD) |
| `end_date` | `str` | `null` | On or before (YYYY-MM-DD) |
| `transaction_type` | `str` | `null` | `"expense"`, `"income"`, or `"transfer"` |
| `min_amount` | `float` | `null` | Minimum amount |
| `max_amount` | `float` | `null` | Maximum amount |
| `limit` | `int` | `100` | Max rows returned |

#### `update_transactions`
Bulk-update transactions matching filters. Use `dry_run=true` to preview.

| Argument | Type | Default | Description |
|---|---|---|---|
| `category_id` | `int` | `null` | New category ID to set |
| `description_pattern` | `str` | `null` | SQL LIKE pattern (e.g. "%pizza%") |
| `start_date` | `str` | `null` | Start date filter |
| `end_date` | `str` | `null` | End date filter |
| `dry_run` | `bool` | `true` | Preview only (no changes applied) |

---

### Categories

#### `get_categories`
Get all transaction categories with hierarchy (id, name, parent_id). No arguments.

#### `create_category`
Create a new category, optionally nested under a parent.

| Argument | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *required* | Category name (e.g. "groceries") |
| `parent_id` | `int \| str` | `null` | Parent category ID or name |
| `is_system` | `bool` | `false` | Whether it's a system category |

---

### Payment Methods

#### `get_payment_methods`
List all payment methods (id, name, is_default). No arguments.

#### `get_payment_method_balances`
List all payment methods with balances. No arguments.

#### `create_payment_method`
Create a new payment method.

| Argument | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *required* | Name (e.g. "PayPal", "Cash") |
| `is_default` | `bool` | `false` | Set as default |
| `balance` | `float` | `0.0` | Initial balance |

#### `update_payment_method_balance`
Manually set a payment method's balance.

| Argument | Type | Default | Description |
|---|---|---|---|
| `payment_method_name` | `str` | *required* | Payment method name |
| `new_balance` | `float` | *required* | New balance value |

#### `transfer_between_payment_methods`
Transfer money between two payment methods.

| Argument | Type | Default | Description |
|---|---|---|---|
| `from_method` | `str` | *required* | Source payment method name |
| `to_method` | `str` | *required* | Destination payment method name |
| `amount` | `float` | *required* | Amount to transfer |

#### `record_gain_loss`
Record a gain or loss on a payment method.

| Argument | Type | Default | Description |
|---|---|---|---|
| `payment_method_name` | `str` | *required* | Payment method name |
| `amount` | `float` | *required* | Positive = gain, negative = loss |

---

### Investments

#### `create_investment`
Record a buy or sell trade.

| Argument | Type | Default | Description |
|---|---|---|---|
| `date` | `str` | *required* | Trade date (YYYY-MM-DD) |
| `ticker` | `str` | *required* | Instrument symbol (e.g. "AAPL") |
| `units` | `float` | *required* | Number of units/shares |
| `price_per_unit` | `float` | *required* | Price per unit |
| `trade_type` | `str` | `"buy"` | `"buy"` or `"sell"` |
| `fees` | `float` | `0.0` | Brokerage fees |
| `payment_method_id` | `int` | `null` | Payment method ID |
| `payment_method_name` | `str` | `null` | Payment method name (resolved to ID) |
| `account_id` | `int` | `null` | Associated account ID |
| `currency` | `str` | `"USD"` | Trade currency |
| `broker` | `str` | `null` | Brokerage name |
| `exchange` | `str` | `null` | Stock exchange |
| `notes` | `str` | `null` | Free-text notes |

#### `get_investments`
Query investment trades with filters.

| Argument | Type | Default | Description |
|---|---|---|---|
| `ticker` | `str` | `null` | Filter by symbol (case-insensitive) |
| `trade_type` | `str` | `null` | `"buy"` or `"sell"` |
| `start_date` | `str` | `null` | On or after (YYYY-MM-DD) |
| `end_date` | `str` | `null` | On or before (YYYY-MM-DD) |
| `limit` | `int` | `100` | Max records |

#### `get_portfolio_summary`
Aggregated portfolio summary per ticker with P&L, cost basis, market value, and unrealized gains. No arguments.

#### `get_portfolio`
Detailed portfolio with holdings and optional real-time performance data.

| Argument | Type | Default | Description |
|---|---|---|---|
| `portfolio_id` | `int` | `null` | Target a specific portfolio, or aggregate all |
| `include_performance` | `bool` | `true` | Enrich with current market valuations |

---

### Market Data

#### `fetch_stock`
Fetch real-time stock quote and optional history via Yahoo Finance.

| Argument | Type | Default | Description |
|---|---|---|---|
| `symbol` | `str` | *required* | Ticker symbol (e.g. "AAPL") |
| `include_history` | `bool` | `false` | Append historical price series |
| `period` | `str` | `"1mo"` | History period: "1d", "5d", "1mo", "3mo", "6mo", "1y" |

#### `set_asset_price`
Manually set an asset's current price (for assets not on Yahoo Finance).

| Argument | Type | Default | Description |
|---|---|---|---|
| `ticker` | `str` | *required* | Asset symbol |
| `price` | `float` | *required* | Current price per unit |
| `currency` | `str` | `"USD"` | Currency code |

#### `update_asset_prices`
Refresh prices from Yahoo Finance for all invested tickers (or a subset).

| Argument | Type | Default | Description |
|---|---|---|---|
| `tickers` | `list[str]` | `null` | Specific tickers to update. If omitted, updates all |

---

### Tax

#### `calculate_tax`
Estimate capital gains tax (short-term vs long-term).

| Argument | Type | Default | Description |
|---|---|---|---|
| `sales` | `list[dict]` | *required* | Array of sale records. Each: `{symbol, quantity, proceeds, cost_basis, purchase_date, sale_date}` |
| `tax_rate_short` | `float` | `0.35` | Short-term tax rate |
| `tax_rate_long` | `float` | `0.15` | Long-term tax rate |
| `holding_period_days` | `int` | `365` | Days threshold for long-term classification |

---

### Visualization

#### `generate_plot`
Generate a matplotlib chart, returned as base64 PNG.

| Argument | Type | Default | Description |
|---|---|---|---|
| `plot_type` | `str` | *required* | `"bar"`, `"line"`, `"pie"`, or `"scatter"` |
| `title` | `str` | *required* | Chart title |
| `data` | `list[dict]` | *required* | List of `{x: ..., y: ...}` records |
| `x_key` | `str` | `"x"` | Key for x-axis values in data |
| `y_key` | `str` | `"y"` | Key for y-axis values in data |

#### `create_persistent_plot`
Save a plot to the dashboard for persistent display.

| Argument | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *required* | Plot name/identifier |
| `plot_type` | `str` | `"bar"` | Plot type |
| `title` | `str` | `""` | Display title |
| `x_key` | `str` | `"x"` | X-axis key |
| `y_key` | `str` | `"y"` | Y-axis key |

---

### SQL

#### `execute_sql`
Execute a read-only SQL SELECT query directly on the database.

| Argument | Type | Default | Description |
|---|---|---|---|
| `query` | `str` | *required* | SQL query (SELECT/WITH only) |
| `params` | `dict` | `null` | Query parameters |

---

### Settings

#### `set_currency`
Set the user's base currency.

| Argument | Type | Default | Description |
|---|---|---|---|
| `currency` | `str` | *required* | Currency code (e.g. "EUR", "USD") |

---

## Prompts

### `bulk_category_update`
Guides the agent through a multi-step bulk category update: get categories, preview with dry_run, confirm, apply.

| Argument | Type | Description |
|---|---|---|
| `query` | `str` | Natural language bulk update request |

### `category_inference`
Suggests the appropriate category for a transaction based on its description.

| Argument | Type | Description |
|---|---|---|
| `transaction_description` | `str` | Description of the transaction |
