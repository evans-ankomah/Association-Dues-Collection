"""dues_types and dues_assessments, plus the planned outcome of each assessment for the payments builder.

Outcomes: full, partial, outstanding, waived_full, waived_partial (half waived, rest paid), cancelled.
"""
from datetime import timedelta

from .. import config
from ..core import OFFICE_HOURS, at, money, rand_time, weighted_day


def build(ctx):
    rng = ctx.stream("dues")
    dept = ctx.ref["dept"]
    sessions = ctx.ref["sessions"]
    hod = ctx.ref["staff"]["hod"]

    # A stable "how reliably does this student pay" score, shared across sessions.
    payer_z = {}
    for sidx in (0, 1):
        for m in ctx.ref["memberships"][sidx]:
            payer_z.setdefault(m["user"]["id"], rng.gauss(0, 1))
    ctx.ref["payer_z"] = payer_z

    plans = []
    dues_types = {}
    for sidx, sess in enumerate(sessions):
        fin_sec = ctx.ref["execs"][sidx]["Financial Secretary"]
        closed_at = at(sessions[-1]["cfg"]["starts_on"], 7) if sess["cfg"]["status"] == "closed" else None
        for cfg in config.DUES_TYPES[sess["cfg"]["name"]]:
            created = rand_time(rng, cfg["created_on"], OFFICE_HOURS)
            dt = ctx.add("dues_types", created, closed_at or created, department_id=dept["id"],
                         academic_session_id=sess["row"]["id"], name=cfg["name"], category=cfg["category"],
                         description=cfg["description"], default_amount=money(cfg["amount"]),
                         currency=config.CURRENCY, due_date=cfg["due_date"], is_mandatory=cfg["mandatory"],
                         eligibility_description=cfg["eligibility"], status=cfg["status"], created_by_id=fin_sec["id"])
            dues_types[(sidx, cfg["key"])] = dt

            for m in ctx.ref["memberships"][sidx]:
                if cfg["levels"] and m["level"] not in cfg["levels"]:
                    continue
                left_early = m["status"] in ("transferred", "inactive") and sidx == 0
                if left_early and m["left_on"] <= cfg["created_on"]:
                    continue
                z = payer_z[m["user"]["id"]] - (1.0 if left_early or m["status"] in ("inactive", "suspended") else 0)

                if cfg["mandatory"]:
                    assessed_at = max(created + timedelta(minutes=rng.randint(5, 50)),
                                      m["joined_at"] + timedelta(hours=rng.randint(2, 30)))
                else:
                    if rng.random() > cfg["opt_in"] + 0.08 * z:
                        continue
                    window_end = min(cfg["due_date"], ctx.as_of.date())
                    day = weighted_day(rng, cfg["created_on"], window_end,
                                       lambda d: 2.0 if (d - cfg["created_on"]).days < 10 else 1.0)
                    assessed_at = max(rand_time(rng, day, (8, 22)), created + timedelta(minutes=30))
                if assessed_at > ctx.as_of:
                    continue

                outcome = _outcome(rng, cfg, m["level"], z)
                if left_early and outcome in ("outstanding", "partial"):
                    outcome = "cancelled" if outcome == "outstanding" else outcome
                amount = money(cfg["amount"])
                waived, state, reason, waived_by, waived_at = money(0), "active", None, None, None
                updated = assessed_at
                if outcome.startswith("waived"):
                    waived = amount if outcome == "waived_full" else money(cfg["amount"] / 2)
                    state = "waived" if outcome == "waived_full" else "active"
                    reason = rng.choice(config.WAIVER_REASONS) if outcome == "waived_full" \
                        else config.PARTIAL_WAIVER_REASON
                    waived_by = hod["id"]
                    waived_at = min(assessed_at + timedelta(days=rng.randint(7, 40), hours=rng.randint(0, 6)),
                                    ctx.as_of - timedelta(hours=1))
                    updated = waived_at
                elif outcome == "cancelled":
                    state = "cancelled"
                    updated = at(m["left_on"], 11)
                row = ctx.add("dues_assessments", assessed_at, updated, dues_type_id=dt["id"],
                              department_membership_id=m["row"]["id"], amount_assessed=amount, amount_waived=waived,
                              due_date=cfg["due_date"], assessment_state=state, waiver_reason=reason,
                              assessed_by_id=fin_sec["id"], assessed_at=assessed_at, waived_by_id=waived_by,
                              waived_at=waived_at)
                plans.append({"row": row, "m": m, "cfg": cfg, "sidx": sidx, "outcome": outcome,
                              "payable": amount - waived, "z": z})

    ctx.ref["dues_types"] = dues_types
    ctx.ref["assessment_plans"] = plans


def _outcome(rng, cfg, level, z):
    rates = cfg["rates"]
    if cfg["mandatory"] and rng.random() < rates["waived"]:
        return "waived_full" if rng.random() < 0.7 else "waived_partial"
    full = min(max(rates["full"] + config.LEVEL_PAY_ADJUST[level] + 0.06 * z, 0.02), 0.99)
    u = rng.random()
    if u < full:
        return "full"
    if u < full + rates["partial"]:
        return "partial"
    return "outstanding"
