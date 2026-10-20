"""Subscription rules, including the atomic multi table plan change."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from data.sqlite_repo import SqliteRepo
from domain.clock import now_iso
from domain.errors import ConflictError, NotFoundError, RuleViolationError
from domain.models import Subscription
from observability.tracing import span
from services.idempotency import check_version, replay_or_execute


class SubscriptionsService:
    """Reads and writes on subscriptions."""

    def __init__(self, repo: SqliteRepo) -> None:
        self.repo = repo

    def list_subscriptions(self, account_id: int | None = None) -> list[Subscription]:
        return self.repo.list_subscriptions(account_id)

    def get_subscription(self, subscription_id: int) -> Subscription:
        subscription = self.repo.get_subscription(subscription_id)
        if subscription is None:
            raise NotFoundError(
                f"subscription {subscription_id} does not exist", subscription_id=subscription_id
            )
        return subscription

    def get_subscription_for_account(self, account_id: int) -> Subscription | None:
        subscriptions = self.repo.list_subscriptions(account_id)
        return subscriptions[0] if subscriptions else None

    def cancel_subscription(
        self,
        subscription_id: int,
        expected_version: int | None = None,
        actor: str = "api",
    ) -> Subscription:
        with span("service.subscriptions.cancel", subscription_id=subscription_id):
            with self.repo.transaction():
                subscription = self.get_subscription(subscription_id)
                if subscription.status == "cancelled":
                    raise ConflictError(
                        f"subscription {subscription_id} is already cancelled",
                        subscription_id=subscription_id,
                    )
                check_version(subscription.version, expected_version, "subscription", subscription_id)
                stamp = now_iso()
                if not self.repo.update_subscription(
                    subscription_id,
                    subscription.version,
                    {"status": "cancelled", "cancelled_at": stamp},
                ):
                    raise RuleViolationError(
                        "the subscription was modified while the request was running",
                        subscription_id=subscription_id,
                    )
                self.repo.insert_audit_event(
                    "subscription",
                    subscription_id,
                    "subscription.cancelled",
                    actor,
                    {},
                    stamp,
                )
            return self.get_subscription(subscription_id)

    def change_plan(
        self,
        subscription_id: int,
        new_plan_code: str,
        seats: int | None = None,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
        actor: str = "api",
        fail_hook: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Move a subscription to another plan.

        Everything happens in one SQLite transaction:

        1. the subscription row is updated and its version is bumped
        2. a subscription change record is written
        3. an invoice is created for the difference
        4. an invoice line describes the change
        5. an audit event records what happened

        If any step fails, all of them roll back and the subscription keeps its
        old plan. The ``fail_hook`` argument lets the lab and the tests trigger
        a failure after a given step, so the rollback can be watched.
        """
        with span(
            "service.subscriptions.change_plan",
            subscription_id=subscription_id,
            new_plan_code=new_plan_code,
        ):
            with self.repo.transaction():
                subscription = self.get_subscription(subscription_id)
                target = self.repo.get_plan_by_code(new_plan_code)
                current = self.repo.get_plan(subscription.plan_id)
                account = self.repo.get_account(subscription.account_id)
                new_seats = int(seats if seats is not None else subscription.seats)
                stamp = now_iso()

                def action() -> dict[str, Any]:
                    if subscription.status == "cancelled":
                        raise RuleViolationError(
                            f"subscription {subscription_id} is cancelled and cannot change plan",
                            subscription_id=subscription_id,
                        )
                    if target is None:
                        raise RuleViolationError(
                            f"unknown plan code {new_plan_code!r}", plan_code=new_plan_code
                        )
                    if current is None:
                        raise RuleViolationError(
                            f"subscription {subscription_id} points at a missing plan",
                            subscription_id=subscription_id,
                        )
                    if account is None:
                        raise NotFoundError(
                            f"account {subscription.account_id} does not exist",
                            account_id=subscription.account_id,
                        )
                    if new_seats < 1:
                        raise RuleViolationError(
                            "a subscription needs at least one seat", seats=new_seats
                        )
                    if new_seats > account.seat_limit:
                        raise RuleViolationError(
                            f"account {account.id} allows {account.seat_limit} seats, "
                            f"{new_seats} requested",
                            seat_limit=account.seat_limit,
                            seats=new_seats,
                        )
                    check_version(
                        subscription.version, expected_version, "subscription", subscription_id
                    )

                    delta_cents = (
                        target.monthly_price_cents - current.monthly_price_cents
                    ) * new_seats

                    fields = {"plan_id": target.id, "seats": new_seats}
                    if not self.repo.update_subscription(
                        subscription_id, subscription.version, fields
                    ):
                        raise RuleViolationError(
                            "the subscription was modified while the request was running",
                            subscription_id=subscription_id,
                        )
                    self._hook(fail_hook, "subscription")
                    self.repo.insert_subscription_change(
                        subscription_id=subscription_id,
                        from_plan_code=current.code,
                        to_plan_code=target.code,
                        seats=new_seats,
                        delta_cents=delta_cents,
                        created_at=stamp,
                    )
                    self._hook(fail_hook, "change_record")
                    invoice_number = f"CHG-{stamp[:10].replace('-', '')}-{subscription_id}"
                    subtotal = max(delta_cents, 0)
                    tax = int(subtotal * 0.19)
                    try:
                        invoice_id = self.repo.insert_invoice(
                            account_id=account.id,
                            subscription_id=subscription_id,
                            number=invoice_number,
                            status="open",
                            issued_at=stamp,
                            due_at=stamp,
                            subtotal_cents=subtotal,
                            tax_cents=tax,
                            total_cents=subtotal + tax,
                        )
                    except sqlite3.IntegrityError as exc:
                        raise RuleViolationError(
                            f"a plan change invoice for subscription {subscription_id} "
                            f"and {stamp[:10]} already exists",
                            subscription_id=subscription_id,
                            invoice_number=invoice_number,
                        ) from exc
                    self._hook(fail_hook, "invoice")
                    self.repo.insert_invoice_line(
                        invoice_id=invoice_id,
                        description=(
                            f"Plan change {current.code} to {target.code} for {new_seats} seats"
                        ),
                        quantity=new_seats,
                        unit_price_cents=target.monthly_price_cents - current.monthly_price_cents,
                        amount_cents=delta_cents,
                        period_start=stamp,
                        period_end=stamp,
                    )
                    self._hook(fail_hook, "invoice_line")
                    self.repo.insert_audit_event(
                        "subscription",
                        subscription_id,
                        "subscription.plan_changed",
                        actor,
                        {
                            "from_plan": current.code,
                            "to_plan": target.code,
                            "seats": new_seats,
                            "delta_cents": delta_cents,
                            "invoice_id": invoice_id,
                        },
                        stamp,
                    )
                    self._hook(fail_hook, "audit_event")
                    return {
                        "subscription_id": subscription_id,
                        "account_id": account.id,
                        "from_plan": current.code,
                        "to_plan": target.code,
                        "seats": new_seats,
                        "delta_cents": delta_cents,
                        "invoice_id": invoice_id,
                        "version": subscription.version + 1,
                        "changed_at": stamp,
                    }

                result, replayed = replay_or_execute(
                    self.repo,
                    scope="subscriptions.change_plan",
                    key=idempotency_key,
                    payload={
                        "subscription_id": subscription_id,
                        "new_plan_code": new_plan_code,
                        "seats": new_seats,
                    },
                    action=action,
                )
            result = dict(result)
            result["replayed"] = replayed
            return result

    @staticmethod
    def _hook(fail_hook: Callable[[str], None] | None, step: str) -> None:
        if fail_hook is not None:
            fail_hook(step)
