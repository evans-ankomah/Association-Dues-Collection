"""Load the generated seed data and check balances match seed/validate_umat.py's definition."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from apps.common import seeding
from apps.finance.models import DuesAssessment, DuesBalance, DuesType
from apps.finance.services.balances import totals, with_balances

SEED_DIR = Path(__file__).resolve().parents[3] / "seed" / "output" / "json"
RECEIVED = {"confirmed", "partially_refunded", "refunded"}

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not (SEED_DIR / "users.json").exists(), reason="run python seed/generate_umat.py"),
]


def _load(name):
    return json.loads((SEED_DIR / f"{name}.json").read_text(encoding="utf-8"))


def expected_balances():
    """Independent re-implementation of validate_umat.py's balance rule over the raw JSON."""
    status = {p["id"]: p["payment_status"] for p in _load("payments")}
    processed = {a["id"] for a in _load("payment_adjustments") if a["adjustment_status"] == "processed"}
    reversed_by_allocation = {}
    for x in _load("payment_allocation_adjustments"):
        if x["payment_adjustment_id"] in processed:
            key = x["payment_allocation_id"]
            reversed_by_allocation[key] = reversed_by_allocation.get(key, Decimal(0)) + Decimal(
                x["amount_reversed"]
            )
    paid = {}
    for al in _load("payment_allocations"):
        if status[al["payment_id"]] in RECEIVED:
            net = Decimal(al["amount_allocated"]) - reversed_by_allocation.get(al["id"], Decimal(0))
            paid[al["dues_assessment_id"]] = paid.get(al["dues_assessment_id"], Decimal(0)) + net
    return {
        a["id"]: Decimal(a["amount_assessed"]) - Decimal(a["amount_waived"]) - paid.get(a["id"], Decimal(0))
        for a in _load("dues_assessments")
        if a["assessment_state"] != "cancelled"
    }


def test_every_seed_balance_matches_validator():
    seeding.load(SEED_DIR, "pw")
    expected = expected_balances()
    live = DuesAssessment.objects.exclude(assessment_state="cancelled")
    orm = {str(pk): bal for pk, bal in with_balances(live).values_list("pk", "balance")}
    view = {
        str(pk): bal
        for pk, bal in DuesBalance.objects.exclude(assessment_state="cancelled").values_list(
            "assessment_id", "balance"
        )
    }
    assert orm == expected
    assert view == expected
    assert all(b >= 0 for b in expected.values())

    rates = {
        t.academic_session.name: totals(t.assessments.all()).collection_rate
        for t in DuesType.objects.filter(category="departmental_dues").select_related("academic_session")
    }
    assert 80 < rates["2025/2026"] < 90
    assert 40 < rates["2026/2027"] < 60
