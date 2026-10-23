"""Validate the generated UMaT dataset against the DeptHub workbook rules and print a realism summary.

    python seed/validate_umat.py [--out seed/output]

Exit code 1 if any integrity check fails.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from umat.schema import TABLES  # noqa: E402

# Unique keys from the workbook's "Constraints & Indexes" sheet (None-valued keys are skipped, like partial indexes).
UNIQUE = {
    "users": [("email",)],
    "user_profiles": [("user_id",), ("institution_id", "student_number")],
    "departments": [("institution_id", "code")],
    "academic_sessions": [("institution_id", "name")],
    "department_memberships": [("department_id", "user_id", "academic_session_id")],
    "role_permissions": [("role_id", "permission_id")],
    "roles": [("role_code",)],
    "permissions": [("permission_code",)],
    "payments": [("provider_name", "provider_reference"), ("idempotency_key",)],
    "payment_allocations": [("payment_id", "dues_assessment_id")],
    "receipts": [("payment_id",), ("receipt_number",)],
    "expense_approvals": [("expense_request_id", "step_number")],
    "event_registrations": [("event_id", "department_membership_id")],
    "event_attendance": [("event_id", "department_membership_id")],
    "committee_members": [("committee_id", "department_membership_id")],
    "webhook_events": [("provider_name", "provider_event_id")],
    "payment_allocation_adjustments": [("payment_adjustment_id", "payment_allocation_id")],
}
# Fields that record something that already happened, so they cannot be after the snapshot.
PAST_FIELDS = {"created_at", "updated_at", "confirmed_at", "initiated_at", "allocated_at", "issued_at", "paid_on",
               "processed_at", "received_at", "occurred_at", "sent_at", "read_at", "checked_in_at", "registered_at",
               "submitted_at", "resolved_at", "verified_at", "joined_on", "left_on", "last_login_at", "acted_at",
               "approved_at", "waived_at", "assessed_at", "completed_at", "decided_at", "incurred_on", "cancelled_at",
               "joined_at", "left_at"}
PHONE = re.compile(r"^233\d{9}$")


class Report:
    def __init__(self):
        self.errors = []

    def check(self, ok, msg):
        if not ok:
            self.errors.append(msg)

    def check_rows(self, rows, pred, label, limit=3):
        bad = [r for r in rows if not pred(r)]
        for r in bad[:limit]:
            self.errors.append(f"{label}: {r.get('id')}")
        if len(bad) > limit:
            self.errors.append(f"{label}: ... {len(bad) - limit} more")


def load(out):
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    data = {}
    for table in manifest["row_counts"]:
        data[table] = json.loads((out / "json" / f"{table}.json").read_text(encoding="utf-8"))
    return manifest, data


def D(v):
    return Decimal(v) if v is not None else Decimal(0)


def validate(manifest, data):
    rep = Report()
    as_of = manifest["as_of"].replace("+00:00", "Z")
    ids = {t: {r["id"] for r in rows} for t, rows in data.items()}

    # --- schema-level checks ---------------------------------------------------------------
    for table, rows in data.items():
        cols = TABLES[table]
        for r in rows:
            rep.check(set(r) == set(cols), f"{table}.{r.get('id')}: column set differs from workbook")
        for col, spec in cols.items():
            if spec["required"]:
                rep.check_rows(rows, lambda r: r[col] is not None and r[col] != "", f"{table}.{col} required")
            if "enum" in spec:
                rep.check_rows(rows, lambda r: r[col] is None or r[col] in spec["enum"], f"{table}.{col} enum")
            if "fk" in spec:
                target = ids.get(spec["fk"], set())
                rep.check_rows(rows, lambda r: r[col] is None or r[col] in target, f"{table}.{col} FK -> {spec['fk']}")
            if col in PAST_FIELDS:
                rep.check_rows(rows, lambda r: r[col] is None or str(r[col]) <= as_of, f"{table}.{col} after AS_OF")
            if spec["type"].startswith("char(3)") and "currency" in col:
                rep.check_rows(rows, lambda r: r[col] in (None, "GHS"), f"{table}.{col} not GHS")
        rep.check_rows(rows, lambda r: r["created_at"] <= r["updated_at"], f"{table} created_at > updated_at")
    for table, keys in UNIQUE.items():
        for key in keys:
            seen = Counter(tuple(r[k] for k in key) for r in data.get(table, []) if all(r[k] is not None for k in key))
            dups = [k for k, n in seen.items() if n > 1]
            rep.check(not dups, f"{table} unique{key} violated: {dups[:3]}")

    # --- business rules -------------------------------------------------------------------------
    sessions = data["academic_sessions"]
    rep.check(sum(s["is_current"] for s in sessions) <= 1, "more than one current session")
    rep.check_rows(sessions, lambda s: s["ends_on"] >= s["starts_on"], "session ends before it starts")
    rep.check_rows(data["users"], lambda u: u["email"] == u["email"].lower(), "email not lowercase")
    rep.check_rows(data["user_profiles"], lambda p: p["phone_number"] is None or PHONE.match(p["phone_number"]),
                   "phone not 233XXXXXXXXX")
    roles = {r["id"]: r for r in data["roles"]}
    rep.check_rows(data["role_assignments"],
                   lambda a: (roles[a["role_id"]]["scope_type"] == "department") == (a["department_id"] is not None),
                   "role assignment scope mismatch")
    rep.check_rows(data["role_assignments"], lambda a: a["ends_at"] is None or a["ends_at"] > a["starts_at"],
                   "role assignment ends before start")
    rep.check_rows(data["events"], lambda e: e["ends_at"] > e["starts_at"], "event ends before start")

    assessments = {a["id"]: a for a in data["dues_assessments"]}
    rep.check_rows(data["dues_assessments"], lambda a: D(0) <= D(a["amount_waived"]) <= D(a["amount_assessed"]),
                   "waived outside 0..assessed")
    rep.check_rows(data["dues_assessments"], lambda a: D(a["amount_waived"]) == 0 or a["waiver_reason"],
                   "waiver without reason")
    memberships = {m["id"]: m for m in data["department_memberships"]}
    dues_types = {d["id"]: d for d in data["dues_types"]}
    rep.check_rows(data["dues_assessments"],
                   lambda a: memberships[a["department_membership_id"]]["academic_session_id"] ==
                   dues_types[a["dues_type_id"]]["academic_session_id"], "assessment session mismatch")
    payments = {p["id"]: p for p in data["payments"]}
    rep.check_rows(data["payments"], lambda p: D(p["amount"]) > 0, "payment amount <= 0")
    rep.check_rows(data["payments"], lambda p: (p["confirmed_at"] is not None) ==
                   (p["payment_status"] in ("confirmed", "refunded", "partially_refunded")), "confirmed_at mismatch")
    alloc_by_payment = defaultdict(Decimal)
    for a in data["payment_allocations"]:
        alloc_by_payment[a["payment_id"]] += D(a["amount_allocated"])
        rep.check(payments[a["payment_id"]]["payment_status"] not in ("failed", "cancelled"),
                  f"allocation on failed/cancelled payment {a['id']}")
    for pid, total in alloc_by_payment.items():
        rep.check(total <= D(payments[pid]["amount"]), f"allocations exceed payment {pid}")
    rep.check_rows(data["receipts"], lambda r: payments[r["payment_id"]]["payment_status"] in
                   ("confirmed", "refunded", "partially_refunded"), "receipt for unconfirmed payment")
    rep.check_rows(data["expenses"], lambda e: e["expense_status"] != "paid" or e["paid_on"], "paid expense w/o paid_on")

    # Balance = assessed - waived - confirmed allocations + processed reversals (workbook formula).
    reversed_by_alloc = defaultdict(Decimal)
    processed = {a["id"] for a in data.get("payment_adjustments", []) if a["adjustment_status"] == "processed"}
    for x in data.get("payment_allocation_adjustments", []):
        if x["payment_adjustment_id"] in processed:
            reversed_by_alloc[x["payment_allocation_id"]] += D(x["amount_reversed"])
    paid = defaultdict(Decimal)
    counted = {"confirmed", "refunded", "partially_refunded"}
    for a in data["payment_allocations"]:
        if payments[a["payment_id"]]["payment_status"] in counted:
            paid[a["dues_assessment_id"]] += D(a["amount_allocated"]) - reversed_by_alloc[a["id"]]
    balances = {}
    for aid, a in assessments.items():
        if a["assessment_state"] == "cancelled":
            continue
        balances[aid] = D(a["amount_assessed"]) - D(a["amount_waived"]) - paid[aid]
        rep.check(balances[aid] >= 0, f"assessment overpaid {aid}: {balances[aid]}")
    return rep, balances


def summary(data, balances):
    sessions = {s["id"]: s["name"] for s in data["academic_sessions"]}
    memberships = {m["id"]: m for m in data["department_memberships"]}
    dues_types = {d["id"]: d for d in data["dues_types"]}
    print("\nMembers per session / level / status")
    c = Counter((sessions[m["academic_session_id"]], m["level_code"], m["membership_status"])
                for m in memberships.values())
    for k in sorted(c):
        print(f"  {k[0]}  {k[1]:<10} {k[2]:<12} {c[k]:>4}")

    print("\nCollection by dues type (assessed / waived / collected / outstanding, GHS)")
    agg = defaultdict(lambda: [Decimal(0)] * 5)
    for a in data["dues_assessments"]:
        if a["id"] not in balances:
            continue
        t = agg[a["dues_type_id"]]
        t[0] += Decimal(a["amount_assessed"])
        t[1] += Decimal(a["amount_waived"])
        t[3] += balances[a["id"]]
        t[4] += 1
        t[2] = t[0] - t[1] - t[3]
    for did, (assessed, waived, collected, outstanding, n) in agg.items():
        d = dues_types[did]
        rate = collected / (assessed - waived) * 100 if assessed > waived else 0
        print(f"  {sessions[d['academic_session_id']]}  {d['name'][:44]:<44} n={n:>4}  {assessed:>10}  {waived:>7}  "
              f"{collected:>10}  {outstanding:>9}  {rate:5.1f}%")

    print("\nCollection rate on departmental dues by level")
    by_level = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for a in data["dues_assessments"]:
        d = dues_types[a["dues_type_id"]]
        if d["category"] != "departmental_dues" or a["id"] not in balances:
            continue
        m = memberships[a["department_membership_id"]]
        key = (sessions[d["academic_session_id"]], m["level_code"])
        payable = Decimal(a["amount_assessed"]) - Decimal(a["amount_waived"])
        by_level[key][0] += payable
        by_level[key][1] += payable - balances[a["id"]]
    for k in sorted(by_level):
        payable, coll = by_level[k]
        print(f"  {k[0]}  {k[1]:<10} {coll / payable * 100:5.1f}%")

    pays = data["payments"]
    print("\nPayments by method / status")
    for k, n in sorted(Counter((p["payment_method"], p["payment_status"]) for p in pays).items()):
        print(f"  {k[0]:<14} {k[1]:<19} {n:>5}")

    print("\nConfirmed collections by month (GHS)")
    month = defaultdict(Decimal)
    for p in pays:
        if p["payment_status"] in ("confirmed", "refunded", "partially_refunded"):
            month[p["confirmed_at"][:7]] += Decimal(p["amount"])
    refunds = sum((Decimal(a["amount"]) for a in data.get("payment_adjustments", [])
                   if a["adjustment_status"] == "processed"), Decimal(0))
    for k in sorted(month):
        print(f"  {k}  {month[k]:>10}  {'#' * int(month[k] / 1000)}")

    spent = sum((Decimal(e["amount"]) for e in data["expenses"] if e["expense_status"] == "paid"), Decimal(0))
    income = sum(month.values(), Decimal(0)) - refunds
    print(f"\nIncome (net of refunds) {income}  |  paid expenses {spent}  |  cash position {income - spent}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    parser.add_argument("--quiet", action="store_true", help="skip the realism summary")
    args = parser.parse_args()
    manifest, data = load(Path(args.out))
    rep, balances = validate(manifest, data)
    if not args.quiet:
        summary(data, balances)
    print()
    if rep.errors:
        print(f"FAILED: {len(rep.errors)} integrity problem(s)")
        for e in rep.errors[:60]:
            print("  -", e)
        sys.exit(1)
    print(f"OK: {sum(manifest['row_counts'].values())} rows in {len(data)} tables passed all integrity checks.")


if __name__ == "__main__":
    main()
