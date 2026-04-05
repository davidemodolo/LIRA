from contextlib import contextmanager

import pytest

# we will just import the underlying functions directly
from lira.mcp import tools


@pytest.fixture(autouse=True)
def mock_db_session(session, monkeypatch):
    @contextmanager
    def mock_session():
        yield session

    monkeypatch.setattr(tools, "DatabaseSession", mock_session)


@pytest.mark.asyncio
async def test_create_account(session):
    result = await tools.create_account(
        name="Test Account",
        account_type="checking",
        balance=1500.50,
    )

    assert "id" in result
    assert result["name"] == "Test Account"


@pytest.mark.asyncio
async def test_list_accounts(session, sample_account):
    result = await tools.list_accounts(active_only=False)
    assert len(result) >= 1
    assert any(a["name"] == sample_account.name for a in result)


@pytest.mark.asyncio
async def test_create_transaction(
    session, sample_account, sample_category, sample_payment_method
):
    result = await tools.create_transaction(
        account_id=sample_account.id,
        category_id=sample_category.id,
        secondary_category_id=sample_category.id,
        payment_method_id=sample_payment_method.id,
        transaction_type="expense",
        amount=12.34,
        description="Coffee",
        merchant="Starbucks",
    )

    assert "id" in result
    assert result["amount"] == 12.34


@pytest.mark.asyncio
async def test_get_transactions(session, multiple_transactions, sample_account):
    result = await tools.get_transactions(account_id=sample_account.id, limit=10)
    data = result["data"]
    assert len(data) >= len(multiple_transactions)
    descriptions = [t["description"] for t in data]
    assert "Salary" in descriptions
