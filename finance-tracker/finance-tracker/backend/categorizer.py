import re
from typing import Tuple, Optional
from sqlalchemy.orm import Session
from .database import Category, CategoryRule


class Categorizer:
    def __init__(self, db: Session):
        self.db = db
        self._rules_cache: Optional[list] = None

    def _load_rules(self) -> list:
        rules = (
            self.db.query(CategoryRule, Category)
            .join(Category, CategoryRule.category_id == Category.id)
            .order_by(CategoryRule.priority.desc(), CategoryRule.match_count.desc())
            .all()
        )
        return rules

    def categorize(self, description: str, amount: int) -> Tuple[str, float]:
        """
        Returns (category_name, confidence 0.0-1.0).
        confidence < 0.7 means flagged for review.
        amount in cents: positive = expense, negative = income/credit.
        """
        desc_upper = description.upper().strip()

        # If amount is negative (income/credit), lean toward Income
        if amount < 0:
            # Still try to match rules first
            pass

        rules = self._load_rules()

        best_category = None
        best_confidence = 0.0

        for rule, category in rules:
            try:
                if re.search(rule.pattern, desc_upper, re.IGNORECASE):
                    # Base confidence from priority
                    base_confidence = min(0.95, 0.70 + (rule.priority / 100.0))
                    # Boost by match_count (learned rules)
                    learned_boost = min(0.05, rule.match_count * 0.001)
                    confidence = base_confidence + learned_boost

                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_category = category.name
            except re.error:
                continue

        # Negative amounts with no match → likely Income
        if best_category is None and amount < 0:
            best_category = "Income"
            best_confidence = 0.5

        if best_category is None:
            best_category = "Other"
            best_confidence = 0.3

        return best_category, round(best_confidence, 2)

    def learn(self, description: str, category_name: str):
        """Update match counts for rules that matched this description."""
        desc_upper = description.upper().strip()
        rules = self._load_rules()
        category = self.db.query(Category).filter_by(name=category_name).first()
        if not category:
            return

        matched = False
        for rule, cat in rules:
            if cat.name == category_name:
                try:
                    if re.search(rule.pattern, desc_upper, re.IGNORECASE):
                        rule.match_count += 1
                        matched = True
                except re.error:
                    continue

        # If no existing rule matched, create a learned rule
        if not matched:
            # Use the first word(s) as pattern for learning
            words = desc_upper.split()
            if words:
                pattern = re.escape(words[0])
                if len(words) > 1:
                    pattern = re.escape(" ".join(words[:2]))
                new_rule = CategoryRule(
                    pattern=pattern,
                    category_id=category.id,
                    priority=5,
                    match_count=1,
                )
                self.db.add(new_rule)

        self.db.commit()
        self._rules_cache = None  # invalidate cache

    def get_all_categories(self) -> list:
        return self.db.query(Category).all()
