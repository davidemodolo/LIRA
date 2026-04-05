# Project Specification: L.I.R.A.
**L.I.R.A. (LIRA Is Recursive Accounting** *or* **LIRA Interprets Requests Accurately)**  
*An AI-native, agentic personal finance and investment tracker. (A nod to the creator's Italian roots and the financial nature of the tool).*

**Vision Statement:** This specification outlines the complete, long-term vision for L.I.R.A. While initial development will focus on core database and LLM interactions, the architecture is designed to support the advanced autonomous loops, human-in-the-loop safeguards, and comprehensive investment tracking detailed below.

---

### 1. System Architecture & Tech Stack
*   **Backend Language:** Python 3.10+
*   **Database:** SQLite (ideal for single-user, file-based portability) managed via an ORM (e.g., SQLAlchemy) to prevent SQL injection and abstract queries.
*   **Agentic Layer (Model Context Protocol - MCP):** The system utilizes an MCP Server architecture to modularize capabilities. Instead of a monolithic backend, the server exposes:
    *   **Tools:** Standardized functions the LLM can call (e.g., `execute_sql_select`, `execute_sql_mutate`, `fetch_yfinance_data`, `generate_python_plot`).
    *   **Prompts/Contexts:** Dedicated interaction templates based on user intent (e.g., `insert_context`, `edit_context`, `analysis_context`, `investment_context`).
*   **API Layer:** FastAPI to handle communication between the client(s), the MCP server, and the core logic.
*   **Clients:**
    *   **CLI:** Python-based terminal interface (using libraries like Rich or Textual for UI).
    *   **Web Dashboard:** A lightweight frontend (e.g., React, Vue, or HTMX) for advanced data visualization, diff approvals, and chat interfaces.
*   **AI Integration:** Integration with advanced LLM APIs (e.g., OpenAI, Anthropic) utilizing Function Calling / Tool Use driven by the MCP framework.

---

### 2. Core Modules & Features

#### A. The LIRA Agentic Loop (Recursive Execution & Multi-Step Reasoning)
Unlike traditional one-shot LLM wrappers, L.I.R.A. operates on a recursive "ReAct" (Reason + Act) loop. The agent can plan multi-step workflows, evaluate its own output, and self-correct.
*   **Self-Correction:** If the user asks for specific data and the agent writes an SQL query that returns `0` results or a syntax error, the agent will catch the error, re-evaluate its logic (e.g., fixing date formats or loosening filters), and re-run the query autonomously before responding to the user.
*   **Multi-Task Chaining:** For a prompt like: *"Take the last 3 weeks, find all meals related to the canteen, and send me a plot of daily spending,"* the agent will:
    1. Translate natural language to SQL to fetch the data.
    2. Analyze the returned dataset.
    3. Call a plotting tool (e.g., writing a quick Pandas/Matplotlib script) to generate the chart.
    4. Return the final visual and textual summary to the user.

#### B. Investment & Portfolio Tracking Engine
L.I.R.A. goes beyond expense tracking to act as an intelligent portfolio manager.
*   **Natural Language Trade Logging:** The user can input trades conversationally: *"I bought 15 shares of AAPL today at $150 each, plus a $2 fee."*
*   **Cost Basis & Metrics:** The system automatically calculates and maintains running totals for average share price, total quantities, and realized vs. unrealized P&L.
*   **External API Integration (yfinance via MCP):** The agent can autonomously ping Yahoo Finance (or similar APIs) to fetch real-time market data to value the current portfolio.
*   **Tax Computation & Strategy:** The LLM can calculate estimated taxes on capital gains by applying regional tax rules to realized profits, distinguishing between short-term and long-term capital gains based on the holding period of specific lots (e.g., FIFO or LIFO accounting).

#### C. Human-in-the-Loop (HITL) Diff Engine & State Management
L.I.R.A. operates autonomously but never executes destructive or mutating actions without human consent.
*   **Pre-Commit Diffing:** Before executing any modifying query (INSERT, UPDATE, DELETE), the backend generates a simulated "Dry Run" state.
*   **Visual Representation:** The client receives a payload containing the `current_state` and the `proposed_state`. It renders a side-by-side or inline diff (similar to Git diffs in VS Code), showing exactly which rows and columns will change.
*   **Interactive Confirmation:** The user can accept the diff entirely, reject it, or reply with further natural language instructions to tweak the proposed changes (e.g., *"Keep it, but change the category to 'Groceries' instead of 'Dining', and apply this to the next 5 transactions too"*).

#### D. Git-like Database Versioning
*   **Transaction Logging:** The system implements a custom version control layer over the database, utilizing Event Sourcing (an append-only log of all financial events) or frequent database snapshotting tools.
*   **Instant Rollbacks:** If an autonomous bulk update behaves unexpectedly (e.g., an LLM misunderstands *"Halve all lunch expenses"*), the user can simply tell L.I.R.A. to *"Undo the last commit,"* instantly reverting the `.sqlite` file to its previous state.

#### E. Granular Data Retrieval & Dynamic Analytics
*   **Hyper-Specific Queries:** The agent can translate deeply complex requests into SQL (e.g., *"Show expenses on even days last month in categories A, B, C only if cost > €3"*).
*   **Dynamic UI Generation:** The web dashboard consumes REST endpoints to render dynamic charts. Instead of hard-coded dashboard widgets, the UI components are dynamically populated by the dataframes the LLM agent prepares in real-time.

#### F. Automation & Ingestion
*   **Recurring Transactions (Cron/Scheduler):** A daemon handles recurring subscriptions based on LLM-extracted rules (e.g., extracting a cron schedule from *"I pay $10 for Spotify on the 5th of every month"*).
*   **CSV Parsing & ETL:** The system accepts raw CSV dumps from banks. The agentic loop processes the unstructured rows, auto-categorizes merchants (using zero-shot classification), formats the data, and queues the entire batch into the HITL "Diff Engine" for a single user approval before final insertion.