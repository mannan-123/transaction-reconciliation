# FinRecon AI — Transaction Reconciliation App

A production-ready financial transaction reconciliation system inspired by QuickBooks, built with FastAPI + Python backend and a beautiful dark UI.

## Features

- **3-Pass Matching Engine**: Exact → Tolerance (±1%) → Fuzzy reference matching
- **QuickBooks-Style Summary Table**: Beginning/ending balances, payments, deposits with difference column
- **KPI Dashboard**: Match rates, exception counts, confidence scores
- **Searchable & Paginated Tables**: Matched transactions and exceptions
- **Priority Flagging**: High/Medium/Low for unmatched transactions
- **Demo Mode**: Runs with built-in synthetic data instantly

## Local Setup

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# Open http://localhost:8000
```

## CSV Format

**Bank Statement columns** (minimum):
`transaction_id, date, amount, reference, description, transaction_type`

**Ledger columns** (minimum):
`transaction_id, date, amount, reference, description, transaction_type`
