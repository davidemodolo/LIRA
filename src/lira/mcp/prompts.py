"""MCP prompts for L.I.R.A."""

from lira.mcp.server import mcp


@mcp.prompt()
def financial_analysis(query: str) -> str:
    """A prompt to analyze financial data."""
    return f"Please analyze this financial query using the available tools: {query}"


@mcp.prompt()
def bulk_category_update(query: str) -> str:
    """A prompt for bulk category updates.

    Use this when the user wants to update multiple transactions at once,
    for example: "change all grocery transactions from last month to FOOD - Groceries"

    Args:
        query: The natural language bulk update request

    Returns:
        A prompt string for bulk operations
    """
    return f"""The user wants to perform a bulk category update. Parse their request and use update_transactions tool.

Available actions:
- Update category for transactions matching a description pattern and date range
- Preview changes with dry_run=True before applying

Example user requests this prompt handles:
- "Go back 2 months and change all 'pizza' entries to FOOD > bar-restaurant"
- "Find all transactions with 'grocery' in description and change them to FOOD > groceries"
- "Change all my bar expenses last month to FOOD > bar-restaurant"

Steps:
1. First use get_categories to find the target category_id
2. Use update_transactions with dry_run=True to preview matches
3. Confirm with user if the preview looks correct
4. Run again with dry_run=False to apply changes

User request: {query}"""


@mcp.prompt()
def category_inference(transaction_description: str) -> str:
    """A prompt to infer the appropriate category for a transaction.

    Use this to help the LLM suggest the correct category when adding transactions.

    Args:
        transaction_description: Description of the transaction

    Returns:
        A prompt string for category inference
    """
    return f"""Based on this transaction description, suggest the most appropriate category:

Transaction: {transaction_description}

Available categories (use get_categories to see full list):
- HOUSE: rent, bills, home-stuff, phone
- RIDES: fuel, car, transport
- HEALTH: meds, sport, visits, barber
- WORK: workservices, workfood
- MISC.: events-culture, personalcare, subscriptions, gifts, gadgets, travel, other, tax-fees
- FOOD: bar-restaurant, groceries
- HOBBY: books-comics, tradingcards, videogames, rnd-hobby

Respond with just the category name (e.g., "FOOD > bar-restaurant" or "FOOD > groceries")."""
