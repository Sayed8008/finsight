"""Budget rules, and assembling a budget with its utilisation.

Three rules live here:

  * a budget belongs to an **expense** category. "Spend no more than X on
    Salary" is not a sentence anyone means, and every figure this service
    computes — spent, remaining, percentage — is a sum of expenses;
  * budgets for one category may not **overlap in time**. The unique
    constraint in the schema only catches an exactly repeated period, which
    leaves the genuinely confusing case open: two budgets both covering today
    would give "how much is left for Food?" two different answers, and the
    dashboard would have to pick one arbitrarily;
  * a budget's category must belong to the caller, and must be active when it
    is first attached.

Spent, remaining, percentage and status are calculated on every read (ADR-015),
by `budget_utilisation`, from one aggregate query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.money import ZERO
from app.models.budget import Budget
from app.models.category import Category
from app.models.enums import CategoryType
from app.repositories.budget_repository import BudgetRepository
from app.services.budget_utilisation import BudgetStatus, Utilisation
from app.services.category_service import CategoryService

logger = logging.getLogger(__name__)


class BudgetNotFound(NotFound):
    message = "That budget was not found."


class BudgetCategoryMustBeExpense(ValidationFailed):
    message = "A budget can only be set on an expense category."


class OverlappingBudget(Conflict):
    message = (
        "A budget for that category already covers part of this period. "
        "Edit the existing one, or choose dates that do not overlap."
    )


@dataclass(frozen=True)
class BudgetSnapshot:
    """A budget as of a given day: the stored row plus what it computes to.

    Exposes the stored fields as well as the derived ones, so the route can do
    `BudgetResponse.model_validate(snapshot)` and there is no third place
    listing the same field names.
    """

    budget: Budget
    utilisation: Utilisation
    on_day: date

    # ─── Stored ───────────────────────────────────────────────────────────
    @property
    def id(self) -> int:
        return self.budget.id

    @property
    def category(self) -> Category:
        return self.budget.category

    @property
    def amount(self) -> Decimal:
        return self.utilisation.amount

    @property
    def period_start(self) -> date:
        return self.budget.period_start

    @property
    def period_end(self) -> date:
        return self.budget.period_end

    # ─── Computed ─────────────────────────────────────────────────────────
    @property
    def spent(self) -> Decimal:
        return self.utilisation.spent

    @property
    def remaining(self) -> Decimal:
        return self.utilisation.remaining

    @property
    def percentage_used(self) -> Decimal:
        return self.utilisation.percentage_used

    @property
    def status(self) -> BudgetStatus:
        return self.utilisation.status

    @property
    def is_current(self) -> bool:
        """Whether the given day falls inside the period, both ends inclusive."""
        return self.period_start <= self.on_day <= self.period_end

    @property
    def days_remaining(self) -> int | None:
        """Days left including today, or None when the budget is not running.

        None for a finished period *and* for one that has not started: "12 days
        remaining" on a budget that begins next month would be read as time
        left to spend, which it is not.
        """
        if not self.is_current:
            return None
        return (self.period_end - self.on_day).days + 1


class BudgetService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._budgets = BudgetRepository(session)
        self._categories = CategoryService(session)

    # ─── Reading ──────────────────────────────────────────────────────────

    def list_budgets(
        self,
        user_id: int,
        *,
        category_id: int | None = None,
        current_only: bool = False,
        today: date | None = None,
    ) -> list[BudgetSnapshot]:
        """Every matching budget, each with its utilisation.

        Two queries in total, whatever the number of budgets: one for the rows
        and one aggregate for the spend against all of them. Computing spend
        per budget would be an N+1 that grows with the user's history.

        `today` is a parameter rather than a call to `date.today()` inside, so
        that "is this budget current" is testable without waiting for the
        calendar.
        """
        on_day = today or date.today()

        budgets = self._budgets.list_for_user(
            user_id,
            category_id=category_id,
            active_on=on_day if current_only else None,
        )
        if not budgets:
            return []

        spend = self._budgets.spend_by_budget(user_id, [budget.id for budget in budgets])
        return [self._snapshot(budget, spend, on_day) for budget in budgets]

    def get(self, user_id: int, budget_id: int, *, today: date | None = None) -> BudgetSnapshot:
        budget = self._budgets.get_for_user(budget_id, user_id)
        if budget is None:
            raise BudgetNotFound

        spend = self._budgets.spend_by_budget(user_id, [budget.id])
        return self._snapshot(budget, spend, today or date.today())

    @staticmethod
    def _snapshot(budget: Budget, spend: dict[int, Decimal], on_day: date) -> BudgetSnapshot:
        return BudgetSnapshot(
            budget=budget,
            utilisation=Utilisation.of(budget.amount, spend.get(budget.id, ZERO)),
            on_day=on_day,
        )

    # ─── Writing ──────────────────────────────────────────────────────────

    def create(
        self, user_id: int, data: dict[str, Any], *, today: date | None = None
    ) -> BudgetSnapshot:
        """Set a budget.

        Pydantic has already checked the amount is positive and the period is
        the right way round. What is left needs the database: does the category
        belong to this user, is it an expense category, is it still active, and
        does the period collide with a budget that already exists.
        """
        category = self._categories.get(user_id, data["category_id"])
        self._require_expense_category(category)
        CategoryService.require_active(category)
        self._require_no_overlap(
            user_id, data["category_id"], data["period_start"], data["period_end"]
        )

        budget = Budget(user_id=user_id, **data)

        try:
            self._budgets.add(budget)
            self._session.commit()
        except IntegrityError:
            # The unique constraint on (user, category, start, end) is what
            # decides if two identical budgets are created concurrently. Turning
            # that race into the ordinary error keeps one behaviour, not two.
            self._session.rollback()
            raise OverlappingBudget from None

        logger.info(
            "Created budget id=%s of %s for category id=%s, user id=%s",
            budget.id,
            budget.amount,
            budget.category_id,
            user_id,
        )
        return self.get(user_id, budget.id, today=today)

    def update(
        self,
        user_id: int,
        budget_id: int,
        changes: dict[str, Any],
        *,
        today: date | None = None,
    ) -> BudgetSnapshot:
        """Apply a partial update.

        Every rule is re-checked against the *result* of the change rather than
        against what was sent. Moving one end of the period, or the category,
        can break a rule that the fields being sent say nothing about.
        """
        snapshot = self.get(user_id, budget_id, today=today)
        budget = snapshot.budget

        new_category_id = changes.get("category_id", budget.category_id)
        new_start = changes.get("period_start", budget.period_start)
        new_end = changes.get("period_end", budget.period_end)

        if new_end < new_start:
            # Reachable when only one end is sent — the schema can only compare
            # the two fields when it is given both.
            raise ValidationFailed("The period cannot end before it starts.")

        if new_category_id != budget.category_id:
            category = self._categories.get(user_id, new_category_id)
            self._require_expense_category(category)
            # Only a *change* of category requires an active one, so a budget
            # whose category was later retired stays editable.
            CategoryService.require_active(category)

        self._require_no_overlap(user_id, new_category_id, new_start, new_end, exclude_id=budget.id)

        for field, value in changes.items():
            setattr(budget, field, value)

        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise OverlappingBudget from None

        logger.info(
            "Updated budget id=%s for user id=%s (fields: %s)",
            budget.id,
            user_id,
            ", ".join(sorted(changes)) or "none",
        )
        return self.get(user_id, budget_id, today=today)

    def delete(self, user_id: int, budget_id: int) -> None:
        """Delete a budget.

        A real delete. A budget is a plan, not a record of something that
        happened, and nothing references it — deleting one loses no history.
        """
        budget = self._budgets.get_for_user(budget_id, user_id)
        if budget is None:
            raise BudgetNotFound

        self._budgets.delete(budget)
        self._session.commit()
        logger.info("Deleted budget id=%s for user id=%s", budget_id, user_id)

    # ─── Rules ────────────────────────────────────────────────────────────

    @staticmethod
    def _require_expense_category(category: Category) -> None:
        if category.category_type is not CategoryType.EXPENSE:
            raise BudgetCategoryMustBeExpense

    def _require_no_overlap(
        self,
        user_id: int,
        category_id: int,
        period_start: date,
        period_end: date,
        *,
        exclude_id: int | None = None,
    ) -> None:
        clash = self._budgets.find_overlapping(
            user_id, category_id, period_start, period_end, exclude_id=exclude_id
        )
        if clash is not None:
            raise OverlappingBudget
