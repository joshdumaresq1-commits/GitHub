from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "finance.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False, index=True)
    description = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)  # stored in cents
    account = Column(String)
    account_type = Column(String)  # chequing / credit
    source = Column(String, default="pdf")  # pdf / gmail
    category = Column(String)
    subcategory = Column(String)
    is_reviewed = Column(Boolean, default=False)
    is_duplicate = Column(Boolean, default=False)
    raw_text = Column(Text)
    confidence = Column(Integer, default=0)  # 0-100
    created_at = Column(DateTime, default=datetime.utcnow)
    batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    gmail_message_id = Column(String, nullable=True, unique=True)


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    bank = Column(String)
    account_type = Column(String)
    last_four = Column(String)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    parent_category = Column(String)
    color = Column(String)
    budget_monthly = Column(Integer)  # cents, nullable

    rules = relationship("CategoryRule", back_populates="category")


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id = Column(Integer, primary_key=True, index=True)
    pattern = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"))
    priority = Column(Integer, default=0)
    match_count = Column(Integer, default=0)

    category = relationship("Category", back_populates="rules")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    bank = Column(String)
    account = Column(String)
    imported_at = Column(DateTime, default=datetime.utcnow)
    transaction_count = Column(Integer, default=0)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DEFAULT_CATEGORIES = [
    {"name": "Housing", "color": "#3f51b5", "budget_monthly": 200000},
    {"name": "Groceries", "color": "#4caf50", "budget_monthly": 60000},
    {"name": "Dining", "color": "#ff9800", "budget_monthly": 40000},
    {"name": "Transport", "color": "#2196f3", "budget_monthly": 30000},
    {"name": "Shopping", "color": "#9c27b0", "budget_monthly": 30000},
    {"name": "Entertainment", "color": "#e91e63", "budget_monthly": 20000},
    {"name": "Health", "color": "#00bcd4", "budget_monthly": 20000},
    {"name": "Income", "color": "#8bc34a", "budget_monthly": None},
    {"name": "Transfers", "color": "#607d8b", "budget_monthly": None},
    {"name": "Subscriptions", "color": "#ff5722", "budget_monthly": 10000},
    {"name": "Travel", "color": "#ffc107", "budget_monthly": 50000},
    {"name": "Other", "color": "#9e9e9e", "budget_monthly": None},
]

DEFAULT_RULES = [
    # Groceries
    (r"LOBLAWS|SOBEYS|METRO(?! BY)|FOODLAND|COSTCO|NO FRILLS|FOOD BASICS|SUPERSTORE|REAL CANADIAN|FRESHCO|FARM BOY", "Groceries", 10),
    # Dining
    (r"TIM HORTONS|STARBUCKS|MCDONALDS|SUBWAY|A&W|HARVEYS|PIZZA|SUSHI|RESTAURANT|CAFE|DOORDASH|SKIP THE DISHES|UBER.*EATS|WENDY|BURGER KING|POPEYES|KFC|CHIPOTLE|FIVE GUYS|NANDO", "Dining", 10),
    (r"LCBO|THE BEER STORE|WINE RACK", "Dining", 8),
    # Subscriptions
    (r"NETFLIX|SPOTIFY|APPLE\.COM/BILL|APPLE.*SUBSCRI|GOOGLE.*PLAY|DISNEY\+|DISNEY PLUS|AMAZON PRIME|HULU|CRAVE|PARAMOUNT|YOUTUBE PREMIUM|MICROSOFT 365|ADOBE|DROPBOX|ICLOUD", "Subscriptions", 10),
    # Shopping
    (r"AMAZON(?!.*PRIME)|WALMART|CANADIAN TIRE|HOME DEPOT|IKEA|WINNERS|HOMESENSE|THE BAY|HUDSON BAY|ZARA|H&M|OLD NAVY|GAP|UNIQLO|BEST BUY|BESTBUY|STAPLES|SPORT CHEK|LULULEMON", "Shopping", 10),
    # Transport
    (r"ESSO|PETRO-CANADA|PETRO CANADA|SHELL|SUNOCO|ULTRAMAR|CO-OP GAS|UBER(?!.*EATS)|LYFT|TTC|PRESTO|GO TRANSIT|VIA RAIL|PARKING|IMPARK|GREENP|OC TRANSPO|STM|TRANSLINK", "Transport", 10),
    # Health
    (r"SHOPPERS DRUG|REXALL|PHARMA|GUARDIAN|LIFE LABS|DYNACARE|FITNESS|YOGA|MASSAGE|DENTIST|DENTAL|OPTOM|PHYSIO|DOCTOR|CLINIC|HOSPITAL|MEDICAL|GOODLIFE|PLANET FITNESS", "Health", 10),
    # Housing
    (r"RENT|HYDRO|ENBRIDGE|ROGERS|BELL|TELUS|SHAW|COGECO|PROPERTY TAX|CONDO FEE|HOA|INTACT|DESJARDINS|AVIVA|TD.*INSURANCE|RBC.*INSURANCE|ELECTRICITY|WATER BILL", "Housing", 10),
    # Income
    (r"E-TRANSFER RECEIVED|INTERAC.*RECEIVED|PAYROLL|DIRECT DEPOSIT|EMPLOYER|SALARY|DIVIDEND|INTEREST PAID TO YOU|TAX REFUND", "Income", 10),
    # Transfers
    (r"PAYMENT THANK YOU|INTERNET PAYMENT|ONLINE PAYMENT|TRANSFER TO|TRANSFER FROM|CREDIT CARD PAYMENT|AUTOPAY|AUTO-PAY|BILL PAYMENT|INTERNAL TRANSFER", "Transfers", 10),
    # Entertainment
    (r"CINEPLEX|IMAX|TICKETMASTER|EVENTBRITE|STEAM|XBOX|PLAYSTATION|NINTENDO|APPLE ARCADE|CONCERT|THEATRE|MUSEUM|GALLERY|BOWLING|MINI GOLF|ESCAPE ROOM", "Entertainment", 10),
    # Travel
    (r"AIRBNB|AIR BNB|EXPEDIA|BOOKING\.COM|HOTELS\.COM|DELTA|AIR CANADA|WESTJET|PORTER|UNITED AIRLINES|AMERICAN AIR|SOUTHWEST|MARRIOTT|HILTON|HYATT|SHERATON|HOLIDAY INN|ENTERPRISE|BUDGET RENT", "Travel", 10),
]


def seed_defaults(db):
    existing = {c.name for c in db.query(Category).all()}
    cat_map = {}
    for cat_data in DEFAULT_CATEGORIES:
        if cat_data["name"] not in existing:
            cat = Category(**cat_data)
            db.add(cat)
            db.flush()
            cat_map[cat_data["name"]] = cat.id
        else:
            cat = db.query(Category).filter_by(name=cat_data["name"]).first()
            cat_map[cat_data["name"]] = cat.id

    db.commit()

    if db.query(CategoryRule).count() == 0:
        for pattern, cat_name, priority in DEFAULT_RULES:
            cat_id = cat_map.get(cat_name)
            if cat_id:
                rule = CategoryRule(pattern=pattern, category_id=cat_id, priority=priority)
                db.add(rule)
        db.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()
