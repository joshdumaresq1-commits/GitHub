from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import (
    Account,
    Category,
    CategoryRule,
    ImportBatch,
    Transaction,
    get_db,
    init_db,
)
from .categorizer import Categorizer
from .parsers.base import get_parser, detect_bank

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATEMENTS_DIR = BASE_DIR / "data" / "statements"
STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Finance Tracker", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend files
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


# ─────────────────────────────── Pydantic schemas ──────────────────────────────


class TransactionUpdate(BaseModel):
    category: Optional[str] = None
    subcategory: Optional[str] = None
    is_reviewed: Optional[bool] = None


class BulkCategorize(BaseModel):
    transaction_ids: List[int]
    category: str


class CategoryCreate(BaseModel):
    name: str
    parent_category: Optional[str] = None
    color: str = "#607d8b"
    budget_monthly: Optional[int] = None  # cents


# ─────────────────────────────── Helper functions ──────────────────────────────


def _tx_to_dict(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "date": tx.date,
        "description": tx.description,
        "amount": tx.amount,
        "amount_display": tx.amount / 100,
        "account": tx.account,
        "account_type": tx.account_type,
        "source": tx.source,
        "category": tx.category,
        "subcategory": tx.subcategory,
        "is_reviewed": tx.is_reviewed,
        "is_duplicate": tx.is_duplicate,
        "confidence": tx.confidence,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


def _is_duplicate(db: Session, date: str, description: str, amount: int) -> bool:
    """Check if a transaction already exists within ±3 days with same description and amount."""
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return False

    date_min = (dt - timedelta(days=3)).strftime("%Y-%m-%d")
    date_max = (dt + timedelta(days=3)).strftime("%Y-%m-%d")

    existing = (
        db.query(Transaction)
        .filter(
            Transaction.date >= date_min,
            Transaction.date <= date_max,
            Transaction.description == description,
            Transaction.amount == amount,
        )
        .first()
    )
    return existing is not None


def _import_transactions(db: Session, parsed: list[dict], batch: ImportBatch) -> list[Transaction]:
    """Categorize and insert parsed transactions, skipping duplicates."""
    cat = Categorizer(db)
    inserted = []

    for tx_data in parsed:
        date = tx_data.get("date", "")
        description = tx_data.get("description", "")
        amount = tx_data.get("amount", 0)

        if not date or not description:
            continue

        if _is_duplicate(db, date, description, amount):
            dup_tx = Transaction(
                date=date,
                description=description,
                amount=amount,
                account=tx_data.get("account_hint"),
                account_type=tx_data.get("account_type"),
                source=tx_data.get("source", "pdf"),
                is_duplicate=True,
                is_reviewed=True,
                raw_text=tx_data.get("raw_text"),
                import_batch_id=batch.id,
            )
            db.add(dup_tx)
            continue

        category_name, confidence = cat.categorize(description, amount)
        confidence_int = round(confidence * 100)

        tx = Transaction(
            date=date,
            description=description,
            amount=amount,
            account=tx_data.get("account_hint"),
            account_type=tx_data.get("account_type"),
            source=tx_data.get("source", "pdf"),
            category=category_name,
            confidence=confidence_int,
            is_reviewed=False,
            raw_text=tx_data.get("raw_text"),
            import_batch_id=batch.id,
        )
        db.add(tx)
        inserted.append(tx)

    db.commit()
    return inserted


# ─────────────────────────────── Routes ────────────────────────────────────────


@app.get("/")
def serve_index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": "Finance Tracker API is running. Frontend not found."})


@app.get("/review.html")
def serve_review():
    review_path = FRONTEND_DIR / "review.html"
    if review_path.exists():
        return FileResponse(str(review_path))
    raise HTTPException(status_code=404, detail="review.html not found")


@app.post("/api/debug/pdf-parse")
async def debug_pdf_parse(file: UploadFile = File(...)):
    """Run the parser and return raw parsed transactions for debugging."""
    import tempfile
    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    parser = get_parser(tmp_path)
    bank = parser.bank_name if parser else "NOT DETECTED"

    if parser is None:
        tmp_path.unlink(missing_ok=True)
        return {"bank": bank, "transactions": [], "error": "No parser matched this PDF"}

    try:
        parsed = parser.parse(tmp_path)
    except Exception as e:
        import traceback
        tmp_path.unlink(missing_ok=True)
        return {"bank": bank, "transactions": [], "error": str(e), "traceback": traceback.format_exc()}

    tmp_path.unlink(missing_ok=True)
    return {"bank": bank, "transaction_count": len(parsed), "transactions": parsed}


@app.post("/api/debug/pdf-text")
async def debug_pdf_text(file: UploadFile = File(...)):
    """Extract and return raw text from a PDF for debugging parser issues."""
    import tempfile
    import pdfplumber

    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    pages_text = []
    with pdfplumber.open(str(tmp_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages_text.append({"page": i + 1, "text": text, "lines": text.split("\n")})

    tmp_path.unlink(missing_ok=True)
    return {"filename": file.filename, "page_count": len(pages_text), "pages": pages_text}


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a bank statement PDF, auto-detect bank, parse, and store transactions."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Save PDF
    dest = STATEMENTS_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Detect bank and parse
    parser = get_parser(dest)
    bank_name = parser.bank_name if parser else "Unknown"

    if parser is None:
        return JSONResponse(
            {
                "success": False,
                "bank": "Unknown",
                "message": "Could not detect bank. Please check that this is a supported bank statement.",
                "transactions_imported": 0,
            }
        )

    try:
        parsed = parser.parse(dest)
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "bank": bank_name,
                "message": f"Error parsing PDF: {str(e)}",
                "transactions_imported": 0,
            }
        )

    # Create import batch
    account_hint = parsed[0].get("account_hint") if parsed else None
    batch = ImportBatch(
        filename=file.filename,
        bank=bank_name,
        account=account_hint,
        transaction_count=len(parsed),
    )
    db.add(batch)
    db.flush()

    inserted = _import_transactions(db, parsed, batch)
    batch.transaction_count = len(inserted)
    db.commit()

    return {
        "success": True,
        "bank": bank_name,
        "message": f"Successfully imported {len(inserted)} transactions from {bank_name}",
        "transactions_imported": len(inserted),
        "total_parsed": len(parsed),
        "batch_id": batch.id,
    }


@app.get("/api/transactions")
def get_transactions(
    month: Optional[str] = Query(None, description="YYYY-MM"),
    category: Optional[str] = Query(None),
    account: Optional[str] = Query(None),
    unreviewed_only: bool = Query(False),
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction).filter(Transaction.is_duplicate == False)

    if month:
        q = q.filter(Transaction.date.startswith(month))
    if category:
        q = q.filter(Transaction.category == category)
    if account:
        q = q.filter(Transaction.account == account)
    if unreviewed_only:
        q = q.filter(Transaction.is_reviewed == False)

    total = q.count()
    transactions = q.order_by(Transaction.date.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "transactions": [_tx_to_dict(t) for t in transactions],
    }


@app.patch("/api/transactions/{tx_id}")
def update_transaction(tx_id: int, update: TransactionUpdate, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if update.category is not None:
        old_category = tx.category
        tx.category = update.category
        # Learn from correction if category changed
        if old_category != update.category:
            cat = Categorizer(db)
            cat.learn(tx.description, update.category)

    if update.subcategory is not None:
        tx.subcategory = update.subcategory

    if update.is_reviewed is not None:
        tx.is_reviewed = update.is_reviewed

    db.commit()
    return _tx_to_dict(tx)


@app.get("/api/summary")
def get_summary(month: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Monthly summary: total income, expenses, net, by category."""
    if not month:
        month = datetime.now().strftime("%Y-%m")

    txns = (
        db.query(Transaction)
        .filter(
            Transaction.date.startswith(month),
            Transaction.is_duplicate == False,
        )
        .all()
    )

    total_income = sum(t.amount for t in txns if t.amount < 0)
    total_expenses = sum(t.amount for t in txns if t.amount > 0)

    by_category: dict[str, int] = {}
    for t in txns:
        cat = t.category or "Other"
        by_category[cat] = by_category.get(cat, 0) + t.amount

    net = total_income + total_expenses  # income is negative, so net = income - expenses
    income_abs = abs(total_income)
    savings_rate = round((income_abs - total_expenses) / income_abs * 100, 1) if income_abs > 0 else 0.0

    return {
        "month": month,
        "total_income": abs(total_income),
        "total_expenses": total_expenses,
        "net_savings": -net,  # positive = saved
        "savings_rate": savings_rate,
        "by_category": {k: v for k, v in by_category.items()},
        "transaction_count": len(txns),
    }


@app.get("/api/summary/monthly")
def get_monthly_summary(months: int = Query(5), db: Session = Depends(get_db)):
    """Returns last N months of expense summary by category for chart."""
    result = []
    today = datetime.now()

    for i in range(months - 1, -1, -1):
        dt = today.replace(day=1) - timedelta(days=i * 28)
        month = dt.strftime("%Y-%m")

        txns = (
            db.query(Transaction)
            .filter(
                Transaction.date.startswith(month),
                Transaction.is_duplicate == False,
                Transaction.amount > 0,
            )
            .all()
        )

        by_cat: dict[str, int] = {}
        for t in txns:
            cat = t.category or "Other"
            by_cat[cat] = by_cat.get(cat, 0) + t.amount

        result.append({"month": month, "by_category": by_cat, "total": sum(by_cat.values())})

    return result


@app.get("/api/categories")
def get_categories(month: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """List categories with monthly totals vs budget."""
    if not month:
        month = datetime.now().strftime("%Y-%m")

    categories = db.query(Category).all()

    # Get spending per category this month
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.date.startswith(month),
            Transaction.is_duplicate == False,
            Transaction.amount > 0,
        )
        .all()
    )

    spending: dict[str, int] = {}
    for t in txns:
        cat = t.category or "Other"
        spending[cat] = spending.get(cat, 0) + t.amount

    return [
        {
            "id": c.id,
            "name": c.name,
            "color": c.color,
            "budget_monthly": c.budget_monthly,
            "spent": spending.get(c.name, 0),
            "budget_display": c.budget_monthly / 100 if c.budget_monthly else None,
            "spent_display": spending.get(c.name, 0) / 100,
            "percent": round(spending.get(c.name, 0) / c.budget_monthly * 100, 1)
            if c.budget_monthly
            else None,
        }
        for c in categories
    ]


@app.post("/api/categories")
def create_category(body: CategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Category).filter_by(name=body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Category already exists")

    cat = Category(
        name=body.name,
        parent_category=body.parent_category,
        color=body.color,
        budget_monthly=body.budget_monthly,
    )
    db.add(cat)
    db.commit()
    return {"id": cat.id, "name": cat.name, "color": cat.color, "budget_monthly": cat.budget_monthly}


@app.get("/api/review-queue")
def get_review_queue(db: Session = Depends(get_db)):
    """Transactions needing review: not reviewed or low confidence (<70)."""
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.is_duplicate == False,
            Transaction.is_reviewed == False,
        )
        .order_by(Transaction.confidence.asc(), Transaction.date.desc())
        .all()
    )

    return {
        "total": len(txns),
        "transactions": [_tx_to_dict(t) for t in txns],
    }


@app.post("/api/gmail/sync")
def sync_gmail(label: str = Query("Finance"), db: Session = Depends(get_db)):
    """Trigger Gmail sync for the given label."""
    try:
        from .gmail_sync import GmailSync

        sync = GmailSync()
        sync.authenticate()
        parsed = sync.sync_label(label)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gmail sync error: {str(e)}")

    if not parsed:
        return {"message": "No new transactions found", "imported": 0}

    batch = ImportBatch(
        filename=f"gmail:{label}",
        bank="Gmail",
        account=label,
        transaction_count=0,
    )
    db.add(batch)
    db.flush()

    inserted = _import_transactions(db, parsed, batch)
    batch.transaction_count = len(inserted)
    db.commit()

    return {
        "message": f"Imported {len(inserted)} transactions from Gmail",
        "imported": len(inserted),
    }


@app.get("/api/accounts")
def get_accounts(db: Session = Depends(get_db)):
    """List distinct accounts seen in transactions with approximate balances."""
    accounts_raw = (
        db.query(Transaction.account, Transaction.account_type)
        .filter(Transaction.account.isnot(None))
        .distinct()
        .all()
    )

    result = []
    for account, account_type in accounts_raw:
        txns = (
            db.query(Transaction)
            .filter(Transaction.account == account, Transaction.is_duplicate == False)
            .all()
        )
        balance = sum(t.amount for t in txns)
        last_date = max((t.date for t in txns), default=None)
        result.append(
            {
                "name": account,
                "account_type": account_type,
                "transaction_count": len(txns),
                "net_flow": balance,
                "net_flow_display": balance / 100,
                "last_transaction": last_date,
            }
        )

    return result


@app.post("/api/bulk-categorize")
def bulk_categorize(body: BulkCategorize, db: Session = Depends(get_db)):
    """Apply a category to multiple transaction IDs."""
    # Verify category exists
    cat = db.query(Category).filter_by(name=body.category).first()
    if not cat:
        raise HTTPException(status_code=404, detail=f"Category '{body.category}' not found")

    updated = 0
    for tx_id in body.transaction_ids:
        tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
        if tx:
            tx.category = body.category
            tx.is_reviewed = True
            updated += 1

    db.commit()
    return {"updated": updated, "category": body.category}
