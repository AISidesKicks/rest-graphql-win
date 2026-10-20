"""Invoice and payment rules."""

from __future__ import annotations

from typing import Any

from data.sqlite_repo import SqliteRepo
from domain.clock import now_iso
from domain.errors import NotFoundError, RuleViolationError
from domain.models import Invoice, InvoiceLine, Page, Payment
from observability.tracing import span
from services.idempotency import replay_or_execute


class InvoicesService:
    """Reads and writes on invoices and payments."""

    def __init__(self, repo: SqliteRepo) -> None:
        self.repo = repo

    def list_invoices(
        self,
        account_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Invoice]:
        with span("service.invoices.list", account_id=account_id, status=status, limit=limit):
            return self.repo.list_invoices(
                account_id=account_id, status=status, limit=limit, cursor=cursor
            )

    def get_invoice(self, invoice_id: int) -> Invoice:
        invoice = self.repo.get_invoice(invoice_id)
        if invoice is None:
            raise NotFoundError(f"invoice {invoice_id} does not exist", invoice_id=invoice_id)
        return invoice

    def get_lines(self, invoice_id: int) -> list[InvoiceLine]:
        self.get_invoice(invoice_id)
        return self.repo.list_invoice_lines(invoice_id)

    def get_payments(self, invoice_id: int) -> list[Payment]:
        self.get_invoice(invoice_id)
        return self.repo.list_payments(invoice_id)

    def record_payment(
        self,
        invoice_id: int,
        amount_cents: int,
        method: str = "card",
        idempotency_key: str | None = None,
        actor: str = "api",
    ) -> dict[str, Any]:
        """Record a payment against an invoice.

        The invoice flips to paid when the payments cover the total. A replay
        with the same idempotency key returns the first answer, a replay with a
        different amount is a mismatch.
        """
        with span("service.invoices.record_payment", invoice_id=invoice_id, amount_cents=amount_cents):
            with self.repo.transaction():
                invoice = self.get_invoice(invoice_id)
                stamp = now_iso()

                def action() -> dict[str, Any]:
                    if invoice.status == "void":
                        raise RuleViolationError(
                            f"invoice {invoice_id} is void and cannot be paid",
                            invoice_id=invoice_id,
                        )
                    if amount_cents <= 0:
                        raise RuleViolationError(
                            "a payment needs a positive amount", amount_cents=amount_cents
                        )
                    if method not in {"card", "sepa", "wire", "paypal"}:
                        raise RuleViolationError(
                            f"unknown payment method {method!r}", method=method
                        )
                    paid_so_far = sum(
                        payment.amount_cents
                        for payment in self.repo.list_payments(invoice_id)
                        if payment.status == "succeeded"
                    )
                    if paid_so_far + amount_cents > invoice.total_cents:
                        raise RuleViolationError(
                            f"invoice {invoice_id} has {invoice.total_cents} cents left, "
                            f"{amount_cents} cents were requested",
                            invoice_id=invoice_id,
                            total_cents=invoice.total_cents,
                            paid_cents=paid_so_far,
                        )
                    payment_id = self.repo.insert_payment(
                        invoice_id=invoice_id,
                        amount_cents=amount_cents,
                        method=method,
                        status="succeeded",
                        paid_at=stamp,
                        reference=f"pay_{invoice_id}_{payment_id_hint(invoice_id)}",
                    )
                    total_paid = paid_so_far + amount_cents
                    fields: dict[str, Any] = {}
                    if total_paid >= invoice.total_cents:
                        fields["status"] = "paid"
                        fields["paid_at"] = stamp
                    if not self.repo.update_invoice(
                        invoice_id, invoice.version, fields or {"status": invoice.status}
                    ):
                        raise RuleViolationError(
                            "the invoice was modified while the request was running",
                            invoice_id=invoice_id,
                        )
                    self.repo.insert_audit_event(
                        "invoice",
                        invoice_id,
                        "invoice.payment_recorded",
                        actor,
                        {"amount_cents": amount_cents, "method": method, "payment_id": payment_id},
                        stamp,
                    )
                    updated = self.get_invoice(invoice_id)
                    return {
                        "payment_id": payment_id,
                        "invoice_id": invoice_id,
                        "amount_cents": amount_cents,
                        "method": method,
                        "invoice_status": updated.status,
                        "total_paid_cents": total_paid,
                        "invoice_version": updated.version,
                        "paid_at": updated.paid_at,
                    }

                result, replayed = replay_or_execute(
                    self.repo,
                    scope="invoices.payment",
                    key=idempotency_key,
                    payload={"invoice_id": invoice_id, "amount_cents": amount_cents, "method": method},
                    action=action,
                )
            result = dict(result)
            result["replayed"] = replayed
            return result


def payment_id_hint(invoice_id: int) -> int:
    return int(invoice_id) * 1000
