"""audit_events derived from the finance and access rows already generated (payments, waivers, refunds,
budget and expense decisions, executive role grants)."""


def build(ctx):
    rng = ctx.stream("audit")
    dept_id = ctx.ref["dept"]["id"]
    events = []

    def log(t, actor, action, entity, entity_id, before=None, after=None):
        events.append((t, actor, action, entity, entity_id, before, after))

    for rec in ctx.ref["payments"]:
        p = rec["row"]
        payer = rec["m"]["user"]["id"]
        if p["payment_method"] == "provider":
            log(p["initiated_at"], payer, "finance.payment.initiated", "payments", p["id"],
                after={"amount": p["amount"], "method": "provider", "provider_reference": p["provider_reference"]})
        else:
            log(p["initiated_at"], p["recorded_by_id"], "finance.payment.recorded", "payments", p["id"],
                after={"amount": p["amount"], "method": p["payment_method"], "payment_status": "pending"})
        if p["confirmed_at"]:
            log(p["confirmed_at"], p["verified_by_id"], "finance.payment.confirmed", "payments", p["id"],
                before={"payment_status": "pending"},
                after={"payment_status": "confirmed",
                       "source": "paystack_webhook" if p["payment_method"] == "provider" else "manual_verification"})
        elif p["payment_status"] in ("failed", "cancelled"):
            log(p["updated_at"], p["verified_by_id"], f"finance.payment.{p['payment_status']}", "payments", p["id"],
                before={"payment_status": "pending"}, after={"payment_status": p["payment_status"]})

    for r in ctx.tables["receipts"]:
        if r["receipt_status"] == "voided":
            log(r["updated_at"], None, "finance.receipt.voided", "receipts", r["id"],
                before={"receipt_status": "issued"}, after={"receipt_status": "voided"})

    for a in ctx.tables["dues_assessments"]:
        if a["amount_waived"] > 0:
            log(a["waived_at"], a["waived_by_id"], "dues.assessment.waived", "dues_assessments", a["id"],
                before={"amount_waived": "0.00"}, after={"amount_waived": a["amount_waived"]})

    for d in ctx.tables["dues_types"]:
        log(d["created_at"], d["created_by_id"], "dues.type.created", "dues_types", d["id"],
            after={"name": d["name"], "default_amount": d["default_amount"]})

    for adj in ctx.tables.get("payment_adjustments", []):
        log(adj["created_at"], adj["requested_by_id"], "finance.refund.requested", "payment_adjustments", adj["id"],
            after={"amount": adj["amount"], "adjustment_type": adj["adjustment_type"]})
        log(adj["processed_at"], adj["approved_by_id"], "finance.refund.processed", "payment_adjustments", adj["id"],
            before={"adjustment_status": "approved"}, after={"adjustment_status": "processed"})

    for b in ctx.tables["budgets"]:
        if b["approved_at"]:
            log(b["approved_at"], b["approved_by_id"], "finance.budget.approved", "budgets", b["id"],
                before={"budget_status": "pending_approval"}, after={"budget_status": "approved"})

    for ap in ctx.tables["expense_approvals"]:
        if ap["acted_at"]:
            log(ap["acted_at"], ap["approver_user_id"], f"finance.expense.{ap['decision']}", "expense_requests",
                ap["expense_request_id"], after={"step_number": ap["step_number"], "decision": ap["decision"]})

    for e in ctx.tables["expenses"]:
        if e["expense_status"] == "paid":
            log(e["updated_at"], e["recorded_by_id"], "finance.expense.paid", "expenses", e["id"],
                after={"amount": e["amount"], "paid_on": e["paid_on"]})

    student_role = ctx.ref["roles"]["student_member"]["id"]
    for ra in ctx.tables["role_assignments"]:
        if ra["role_id"] != student_role:
            log(ra["starts_at"], ra["assigned_by_id"], "access.role.assigned", "role_assignments", ra["id"],
                after={"role_id": ra["role_id"], "user_id": ra["user_id"]})

    events.sort(key=lambda e: e[0])
    for t, actor, action, entity, entity_id, before, after in events:
        ctx.add("audit_events", t, department_id=dept_id, actor_user_id=actor, action_key=action, entity_type=entity,
                entity_id=entity_id, before_data=_jsonable(before), after_data=_jsonable(after),
                request_id=f"req_{rng.getrandbits(64):016x}", occurred_at=t)


def _jsonable(data):
    if data is None:
        return None
    return {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v) for k, v in data.items()}

