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

## Free Deployment Options

### Option 1 – Railway (Recommended, fastest)
1. Push this folder to a GitHub repo
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Select your repo — Railway auto-detects the Procfile
4. Done! Free tier = 500 hrs/month

### Option 2 – Render
1. Push to GitHub
2. Go to https://render.com → New → Web Service
3. Connect repo, set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Free tier available

### Option 3 – Fly.io
```bash
fly launch
fly deploy
```

## CSV Format

**Bank Statement columns** (minimum):
`transaction_id, date, amount, reference, description, transaction_type`

**Ledger columns** (minimum):
`transaction_id, date, amount, reference, description, transaction_type`

Amounts: positive = credit/deposit, negative = debit/payment.
