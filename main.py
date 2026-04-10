from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
from io import StringIO, BytesIO
import json
from datetime import datetime
import re
from typing import Optional
import uvicorn
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Recon AI", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── helpers ──────────────────────────────────────────────────────────────────

def clean_reference(text):
    if pd.isna(text):
        return ""
    text = str(text).lower()
    for pat in ["inv-", "pay-", "ref-", "chk-"]:
        text = text.replace(pat, pat[:-1])
    return re.sub(r"[^a-z0-9]", "", text)


def fuzzy_ratio(a: str, b: str) -> float:
    """Simple character-level similarity without external lib."""
    if not a or not b:
        return 0.0
    matches = sum(c1 == c2 for c1, c2 in zip(a, b))
    return (2 * matches) / (len(a) + len(b))

def split_counts(df):
    payments_df = df[df["transaction_type"] == "DEBIT"]
    deposits_df = df[df["transaction_type"] == "CREDIT"]

    payments_sum = payments_df["amount"].abs().sum()
    deposits_sum = deposits_df["amount"].abs().sum()

    payments_count = len(payments_df)
    deposits_count = len(deposits_df)

    return payments_sum, payments_count, deposits_sum, deposits_count

def compute_ending(df):
    deposits = df[df["transaction_type"] == "CREDIT"]["amount"].sum()
    payments = df[df["transaction_type"] == "DEBIT"]["amount"].sum()
    return round(abs(float(deposits - payments)), 2)

def reconcile(bank_df: pd.DataFrame, ledger_df: pd.DataFrame):
    bank = bank_df.copy()
    ledger = ledger_df.copy()

    # Standardise columns to lowercase
    bank.columns = [c.lower().strip() for c in bank.columns]
    ledger.columns = [c.lower().strip() for c in ledger.columns]

    # Date & amount normalisation
    bank["date"] = pd.to_datetime(bank["date"], errors="coerce")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce")
    bank["amount"] = pd.to_numeric(bank["amount"], errors="coerce").round(2)
    ledger["amount"] = pd.to_numeric(ledger["amount"], errors="coerce").round(2)
    bank["ref_clean"] = bank["reference"].apply(clean_reference)
    ledger["ref_clean"] = ledger["reference"].apply(clean_reference)
    bank["amount_abs"] = bank["amount"].abs()
    ledger["amount_abs"] = ledger["amount"].abs()

    # Track which rows have been matched
    bank["_matched"] = False
    ledger["_matched"] = False

    exact_matches, tolerance_matches, fuzzy_matches = [], [], []

    for bi, brow in bank.iterrows():
        if brow["_matched"]:
            continue
        candidates = ledger[(~ledger["_matched"]) & (ledger["date"].between(brow["date"] - pd.Timedelta(days=3), brow["date"] + pd.Timedelta(days=3)))]
        # candidates = ledger[
        #     (~ledger["_matched"]) &
        #     (ledger["transaction_type"] == brow["transaction_type"]) &
        #     (ledger["date"].between(
        #         brow["date"] - pd.Timedelta(days=3),
        #         brow["date"] + pd.Timedelta(days=3)
        #     ))
        # ]

        # Pass 1 – exact reference + amount
        exact = candidates[(candidates["ref_clean"] == brow["ref_clean"]) & (candidates["amount_abs"] == brow["amount_abs"])]
        if not exact.empty:
            li = exact.index[0]
            exact_matches.append({
                "bank_id": brow.get("transaction_id", bi),
                "ledger_id": ledger.loc[li].get("transaction_id", li),
                "date_bank": str(brow["date"].date()),
                "date_ledger": str(ledger.loc[li]["date"].date()),
                "amount_bank": float(brow["amount"]),
                "amount_ledger": float(ledger.loc[li]["amount"]),
                "reference_bank": str(brow.get("reference", "")),
                "reference_ledger": str(ledger.loc[li].get("reference", "")),
                "description": str(brow.get("description", "")),
                "match_type": "Exact",
                "confidence": 100,
                "amount_diff": 0.0,
                "date_diff_days": int(abs((brow["date"] - ledger.loc[li]["date"]).days)),
            })
            bank.at[bi, "_matched"] = True
            ledger.at[li, "_matched"] = True
            continue

        # Pass 2 – amount within tolerance (±1%) + date within 3 days
        tol = candidates[(candidates["amount_abs"].between(brow["amount_abs"] * 0.99, brow["amount_abs"] * 1.01))]
        # tol = candidates[
        #     (candidates["amount_abs"].between(
        #         brow["amount_abs"] * 0.99,
        #         brow["amount_abs"] * 1.01
        #     )) &
        #     (candidates["ref_clean"] == brow["ref_clean"])
        # ]

        if not tol.empty:
            li = tol.index[0]
            diff = abs(brow["amount_abs"] - ledger.loc[li]["amount_abs"])
            tolerance_matches.append({
                "bank_id": brow.get("transaction_id", bi),
                "ledger_id": ledger.loc[li].get("transaction_id", li),
                "date_bank": str(brow["date"].date()),
                "date_ledger": str(ledger.loc[li]["date"].date()),
                "amount_bank": float(brow["amount"]),
                "amount_ledger": float(ledger.loc[li]["amount"]),
                "reference_bank": str(brow.get("reference", "")),
                "reference_ledger": str(ledger.loc[li].get("reference", "")),
                "description": str(brow.get("description", "")),
                "match_type": "Probabilistic",
                "confidence": max(70, 100 - int(diff * 10)),
                "amount_diff": round(float(diff), 2),
                "date_diff_days": int(abs((brow["date"] - ledger.loc[li]["date"]).days)),
            })
            bank.at[bi, "_matched"] = True
            ledger.at[li, "_matched"] = True
            continue

        # Pass 3 – fuzzy reference match
        best_score, best_li = 0, None
        for li2, lrow in candidates.iterrows():
            score = fuzzy_ratio(brow["ref_clean"], lrow["ref_clean"])
            if score > best_score:
                best_score, best_li = score, li2
        if best_score > 0.65 and best_li is not None:
            li = best_li
            diff = abs(brow["amount_abs"] - ledger.loc[li]["amount_abs"])
            fuzzy_matches.append({
                "bank_id": brow.get("transaction_id", bi),
                "ledger_id": ledger.loc[li].get("transaction_id", li),
                "date_bank": str(brow["date"].date()),
                "date_ledger": str(ledger.loc[li]["date"].date()),
                "amount_bank": float(brow["amount"]),
                "amount_ledger": float(ledger.loc[li]["amount"]),
                "reference_bank": str(brow.get("reference", "")),
                "reference_ledger": str(ledger.loc[li].get("reference", "")),
                "description": str(brow.get("description", "")),
                "match_type": "Semantic",
                "confidence": int(best_score * 100),
                "amount_diff": round(float(diff), 2),
                "date_diff_days": int(abs((brow["date"] - ledger.loc[li]["date"]).days)),
            })
            bank.at[bi, "_matched"] = True
            ledger.at[li, "_matched"] = True

    all_matches = exact_matches + tolerance_matches + fuzzy_matches

    unmatched_bank = []
    for bi, brow in bank[~bank["_matched"]].iterrows():
        days_old = (pd.Timestamp.now() - brow["date"]).days if pd.notna(brow["date"]) else 0
        amt = float(brow["amount_abs"])
        priority = "High" if (days_old > 7 or amt > 1000) else ("Low" if (days_old <= 2 and amt <= 100) else "Medium")
        unmatched_bank.append({
            "transaction_id": str(brow.get("transaction_id", bi)),
            "date": str(brow["date"].date()) if pd.notna(brow["date"]) else "",
            "amount": float(brow["amount"]),
            "reference": str(brow.get("reference", "")),
            "description": str(brow.get("description", "")),
            "source": "Bank",
            "days_unmatched": days_old,
            "priority": priority,
        })

    unmatched_ledger = []
    for li, lrow in ledger[~ledger["_matched"]].iterrows():
        days_old = (pd.Timestamp.now() - lrow["date"]).days if pd.notna(lrow["date"]) else 0
        amt = float(lrow["amount_abs"])
        priority = "High" if (days_old > 7 or amt > 1000) else ("Low" if (days_old <= 2 and amt <= 100) else "Medium")
        unmatched_ledger.append({
            "transaction_id": str(lrow.get("transaction_id", li)),
            "date": str(lrow["date"].date()) if pd.notna(lrow["date"]) else "",
            "amount": float(lrow["amount"]),
            "reference": str(lrow.get("reference", "")),
            "description": str(lrow.get("description", "")),
            "source": "Ledger",
            "days_unmatched": days_old,
            "priority": priority,
        })

    # ── Summary stats (QuickBooks-style) ─────────────────────────────────────
    total_bank = len(bank)
    total_ledger = len(ledger)
    matched_bank = total_bank - len(unmatched_bank)
    matched_ledger = total_ledger - len(unmatched_ledger)
    # bank_credits = bank[bank["amount"] > 0]["amount"].sum()
    # bank_debits = bank[bank["amount"] < 0]["amount"].abs().sum()
    # ledger_credits = ledger[ledger["amount"] > 0]["amount"].sum()
    # ledger_debits = ledger[ledger["amount"] < 0]["amount"].abs().sum()

    # Beginning & ending balance (sum approach)
    # beginning_balance = 0.0  # not in data – use 0 as placeholder
    # stmt_ending = round(float(bank["amount"].sum()), 2)
    # qb_ending = round(float(ledger["amount"].sum()), 2)

    # summary = {
    #     "beginning_balance": beginning_balance,
    #     "stmt_payments": round(float(bank_debits), 2),
    #     "stmt_payment_count": int((bank["amount"] < 0).sum()),
    #     "qb_payments": round(float(ledger_debits), 2),
    #     "qb_payment_count": int((ledger["amount"] < 0).sum()),
    #     "stmt_deposits": round(float(bank_credits), 2),
    #     "stmt_deposit_count": int((bank["amount"] > 0).sum()),
    #     "qb_deposits": round(float(ledger_credits), 2),
    #     "qb_deposit_count": int((ledger["amount"] > 0).sum()),
    #     "stmt_ending": stmt_ending,
    #     "qb_ending": qb_ending,
    #     "ending_diff": round(stmt_ending - qb_ending, 2),
    # }
    
    # Bank side
    bank_payments, bank_payment_count, bank_deposits, bank_deposit_count = split_counts(bank)

    # Ledger side
    ledger_payments, ledger_payment_count, ledger_deposits, ledger_deposit_count = split_counts(ledger)

    # Ending balances (correct net calculation)
    # stmt_ending = round(float(bank["amount"].sum()), 2)
    # qb_ending = round(float(ledger["amount"].sum()), 2)
    
    stmt_ending = compute_ending(bank)
    qb_ending = compute_ending(ledger)

    # Beginning balance (still placeholder if not provided)
    beginning_balance = 0.0

    summary = {
        "beginning_balance": beginning_balance,

        # Payments
        "stmt_payments": round(float(bank_payments), 2),
        "stmt_payment_count": int(bank_payment_count),
        "qb_payments": round(float(ledger_payments), 2),
        "qb_payment_count": int(ledger_payment_count),

        # Deposits
        "stmt_deposits": round(float(bank_deposits), 2),
        "stmt_deposit_count": int(bank_deposit_count),
        "qb_deposits": round(float(ledger_deposits), 2),
        "qb_deposit_count": int(ledger_deposit_count),

        # Ending
        "stmt_ending": stmt_ending,
        "qb_ending": qb_ending,
        "ending_diff": round(stmt_ending - qb_ending, 2),
    }
    
    kpis = {
        "total_bank": total_bank,
        "total_ledger": total_ledger,
        "matched_bank": matched_bank,
        "matched_ledger": matched_ledger,
        "recon_rate_bank": round(matched_bank / total_bank * 100, 1) if total_bank else 0,
        "recon_rate_ledger": round(matched_ledger / total_ledger * 100, 1) if total_ledger else 0,
        "exact_count": len(exact_matches),
        "tolerance_count": len(tolerance_matches),
        "fuzzy_count": len(fuzzy_matches),
        "unmatched_bank_count": len(unmatched_bank),
        "unmatched_ledger_count": len(unmatched_ledger),
        "high_priority": sum(1 for u in unmatched_bank + unmatched_ledger if u["priority"] == "High"),
        "total_value_processed": round(float(bank["amount"].abs().sum()), 2),
        "date_range": f"{bank['date'].min().date()} – {bank['date'].max().date()}" if bank["date"].notna().any() else "N/A",
    }

    return {
        "kpis": kpis,
        "summary": summary,
        "matches": all_matches,
        "unmatched": unmatched_bank + unmatched_ledger,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html") as f:
        return f.read()


@app.get("/api/demo")
async def demo():
    # bank_df, ledger_df = generate_demo_data()
    bank_df = pd.read_csv(os.path.join(BASE_DIR, "data", "bank_statement.csv"))
    ledger_df = pd.read_csv(os.path.join(BASE_DIR, "data", "ledger_transactions.csv"))
    result = reconcile(bank_df, ledger_df)
    return JSONResponse(result)


@app.post("/api/reconcile")
async def run_reconcile(bank_file: UploadFile = File(...), ledger_file: UploadFile = File(...)):
    try:
        bank_bytes = await bank_file.read()
        ledger_bytes = await ledger_file.read()
        bank_df = pd.read_csv(BytesIO(bank_bytes))
        ledger_df = pd.read_csv(BytesIO(ledger_bytes))
    except Exception as e:
        raise HTTPException(400, detail=f"Could not parse CSV files: {e}")
    result = reconcile(bank_df, ledger_df)
    return JSONResponse(result)


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
