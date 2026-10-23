"""budgets, expense_requests, expense_approvals, expenses. Vendor names are fictitious Tarkwa-area businesses."""
from datetime import date, timedelta

from .. import config, ids
from ..core import OFFICE_HOURS, at, money, next_weekday, rand_time

# key, name, category, amount, starts_on, ends_on, status (for the current session; closed session -> closed)
BUDGETS = {
    0: [
        ("orientation", "Freshers' Orientation 2025", "Orientation", 3500, date(2025, 9, 1), date(2025, 10, 31)),
        ("hackathon", "CSE Hackathon 2025", "Academic", 6000, date(2025, 10, 15), date(2025, 11, 30)),
        ("cse_week", "CSE Week 2026", "Events", 26000, date(2026, 2, 1), date(2026, 3, 31)),
        ("visit", "Level 300 Industrial Visit 2026", "Excursion", 24000, date(2026, 2, 1), date(2026, 4, 30)),
        ("dinner", "Final Year Dinner & Awards Night 2026", "Social", 13000, date(2026, 3, 15), date(2026, 5, 31)),
        ("welfare", "Members' Welfare Fund 2025/2026", "Welfare", 5000, date(2025, 8, 25), date(2026, 7, 31)),
        ("admin", "Administration & Communications 2025/2026", "Administration", 3500, date(2025, 8, 25),
         date(2026, 7, 31)),
    ],
    1: [
        ("orientation", "Freshers' Orientation 2026", "Orientation", 4500, date(2026, 9, 1), date(2026, 10, 31),
         "approved"),
        ("hackathon", "CSE Hackathon 2026", "Academic", 7000, date(2026, 10, 15), date(2026, 11, 30), "approved"),
        ("welfare", "Members' Welfare Fund 2026/2027", "Welfare", 6000, date(2026, 8, 24), date(2027, 7, 30),
         "approved"),
        ("admin", "Administration & Communications 2026/2027", "Administration", 4000, date(2026, 8, 24),
         date(2027, 7, 30), "approved"),
        ("cse_week", "CSE Week 2027", "Events", 30000, date(2027, 2, 1), date(2027, 3, 31), "pending_approval"),
        ("dinner", "Final Year Dinner & Awards Night 2027", "Social", 15000, date(2027, 3, 15), date(2027, 5, 31),
         "draft"),
    ],
}

CATERER = "Mama Efua Catering Services, Tarkwa"
PRINTER = "Ebenezer Prints & Graphics, Tarkwa"

# budget key -> [(title, purpose, amount, vendor, days after budget start the money is needed, requester, outcome)]
# outcome: paid | rejected | withdrawn | approved_unpaid | pending_step2 | submitted
REQUESTS = {
    0: {
        "orientation": [
            ("Printing of freshers' handbooks (150 copies)", "Handbooks for Level 100 orientation.", 1650, PRINTER, 10, "Organising Secretary", "paid"),
            ("Refreshments for freshers' orientation", "Snacks and drinks for about 130 attendees.", 1300, CATERER, 15, "Organising Secretary", "paid"),
            ("PA system hire for orientation", "Sound system for the orientation programme.", 400, "Tarkwa Sound & Lights", 15, "Organising Secretary", "paid"),
        ],
        "hackathon": [
            ("Hackathon prizes for top three teams", "1st GHS 2,000; 2nd GHS 1,200; 3rd GHS 800.", 4000, None, 35, "President", "paid"),
            ("Internet data and generator fuel for hackathon", "Data bundles and power backup for the 24-hour event.", 950, "Nana Yaw Enterprise", 30, "Organising Secretary", "paid"),
            ("Hackathon meals", "Meals for about 60 participants over two days.", 1200, CATERER, 34, "Organising Secretary", "paid"),
        ],
        "cse_week": [
            ("CSE Week souvenir T-shirts (240 pieces)", "Production of branded T-shirts ordered by members.", 13200, "Akwaaba Textiles & Branding, Takoradi", 15, "Treasurer", "paid"),
            ("Banners, flyers and roll-up stands", "Publicity materials for CSE Week.", 1450, PRINTER, 20, "Public Relations Officer", "paid"),
            ("Guest speaker honorarium and transport", "Industry speaker travelling from Accra.", 1500, None, 40, "President", "paid"),
            ("Canopies and chairs hire", "Outdoor exhibition day.", 1100, "Golden Canopy Rentals, Tarkwa", 40, "Organising Secretary", "paid"),
            ("Football gala trophies and medals", "Prizes for the inter-level football gala.", 900, "Tarkwa Sports Shop", 42, "Organising Secretary", "paid"),
            ("CSE Week closing night refreshments", "Food and drinks for the closing night.", 3200, CATERER, 44, "Organising Secretary", "paid"),
            ("Branded hoodies for executives", "Hoodies for the executive committee.", 2400, "Akwaaba Textiles & Branding, Takoradi", 25, "Public Relations Officer", "rejected"),
        ],
        "visit": [
            ("Bus hire: two 60-seater coaches", "Return transport Tarkwa - Accra for the industrial visit.", 12800, "Bonsu Transport Services", 60, "Vice President", "paid"),
            ("Accommodation for industrial visit (2 nights)", "Hostel booking for 66 students and 2 staff.", 6900, "Accra Students' Lodge", 60, "Vice President", "paid"),
            ("Feeding for industrial visit", "Meals for three days.", 3900, CATERER, 60, "Vice President", "paid"),
        ],
        "dinner": [
            ("Venue and catering for dinner night", "Hall rental and three-course meal for about 70 guests.", 9800, "Riverside Events Centre, Tarkwa", 45, "Organising Secretary", "paid"),
            ("Award plaques and citations", "Plaques for best students and outgoing executives.", 1600, "Tarkwa Trophies & Engraving", 40, "General Secretary", "paid"),
            ("Photography and videography", "Coverage of the dinner and awards night.", 1200, "Kojo Lens Media", 45, "Public Relations Officer", "paid"),
            ("DJ and MC services", "Entertainment for the dinner night.", 800, None, 45, "Organising Secretary", "withdrawn"),
        ],
        "welfare": [
            ("Hospital support for a member", "Welfare donation for a hospitalised Level 200 member.", 800, None, 70, "Women's Commissioner", "paid"),
            ("Bereavement donation", "Support to a member who lost a parent.", 1000, None, 150, "Women's Commissioner", "paid"),
            ("Contribution to hall social night", "Request to fund a hall-organised party.", 1500, None, 200, "Public Relations Officer", "rejected"),
        ],
        "admin": [
            ("Receipt books and stationery", "Stationery for the executive office.", 380, PRINTER, 8, "Treasurer", "paid"),
            ("Social media data bundles (semester 1)", "Data for association pages and WhatsApp updates.", 300, None, 10, "Public Relations Officer", "paid"),
            ("Social media data bundles (semester 2)", "Data for association pages and WhatsApp updates.", 300, None, 150, "Public Relations Officer", "paid"),
        ],
    },
    1: {
        "orientation": [
            ("Printing of freshers' handbooks (160 copies)", "Handbooks for Level 100 orientation.", 1950, PRINTER, 10, "Organising Secretary", "paid"),
            ("Refreshments for freshers' orientation", "Snacks and drinks for about 140 attendees.", 1700, CATERER, 22, "Organising Secretary", "paid"),
            ("PA system hire for orientation", "Sound system for the orientation programme.", 450, "Tarkwa Sound & Lights", 22, "Organising Secretary", "paid"),
        ],
        "hackathon": [
            ("Hackathon prizes for top three teams", "1st GHS 2,200; 2nd GHS 1,400; 3rd GHS 900.", 4500, None, 30, "President", "approved_unpaid"),
            ("Hackathon meals", "Meals for about 70 participants over two days.", 1400, CATERER, 30, "Organising Secretary", "pending_step2"),
            ("Internet data and generator fuel for hackathon", "Data bundles and power backup for the 24-hour event.", 1000, "Nana Yaw Enterprise", 29, "Organising Secretary", "submitted"),
        ],
        "welfare": [
            ("Hospital support for a member", "Welfare donation for a hospitalised Level 100 member.", 700, None, 40, "Women's Commissioner", "paid"),
        ],
        "admin": [
            ("Receipt books and stationery", "Stationery for the executive office.", 420, PRINTER, 7, "Treasurer", "paid"),
            ("Social media data bundles (semester 1)", "Data for association pages and WhatsApp updates.", 350, None, 9, "Public Relations Officer", "paid"),
        ],
    },
}

REJECTION_NOTES = {"rejected": "Not a priority use of members' dues this session; resubmit if sponsorship is found.",
                   "withdrawn": "Withdrawn by requester: service provided free by a member."}


def build(ctx):
    rng = ctx.stream("finance")
    dept = ctx.ref["dept"]
    sessions = ctx.ref["sessions"]
    staff = ctx.ref["staff"]
    accounts = ctx.ref["accounts"]
    budgets = {}
    voucher = {0: 0, 1: 0}

    for sidx, items in BUDGETS.items():
        execs = ctx.ref["execs"][sidx]
        sess = sessions[sidx]
        sess_start = at(sess["cfg"]["starts_on"], 10)
        closed = sess["cfg"]["status"] == "closed"
        for spec in items:
            key, name, category, amount, starts, ends = spec[:6]
            status = "closed" if closed else spec[6]
            created = max(at(starts, 10) - timedelta(days=14), sess_start + timedelta(days=1))
            if key == "cse_week" and not closed:
                created = at(date(2026, 10, 12), 15)
            if key == "dinner" and not closed:
                created = at(date(2026, 10, 19), 16)
            approved_at = None if status in ("draft", "pending_approval") else \
                rand_time(rng, next_weekday(created.date() + timedelta(days=rng.randint(2, 5))), OFFICE_HOURS)
            updated = at(sessions[-1]["cfg"]["starts_on"], 7) if closed else (approved_at or created)
            budgets[(sidx, key)] = ctx.add(
                "budgets", created, updated, department_id=dept["id"], academic_session_id=sess["row"]["id"],
                name=name, category=category, allocated_amount=money(amount), currency=config.CURRENCY,
                starts_on=starts, ends_on=ends, budget_status=status, proposed_by_id=execs["Treasurer"]["id"],
                approved_by_id=staff["hod"]["id"] if approved_at else None, approved_at=approved_at)

        for bkey, reqs in REQUESTS[sidx].items():
            budget = budgets[(sidx, bkey)]
            for title, purpose, amount, vendor, offset, requester, outcome in reqs:
                needed_by = budget["starts_on"] + timedelta(days=offset)
                submitted = rand_time(rng, next_weekday(needed_by - timedelta(days=rng.randint(10, 18))), (8, 21))
                # Requests still in the workflow were raised recently enough to be mid-approval at AS_OF.
                latest = ctx.as_of - timedelta(days={"approved_unpaid": 9, "pending_step2": 6,
                                                     "submitted": 1}.get(outcome, 0))
                submitted = max(min(submitted, latest), budget["approved_at"] + timedelta(hours=2))
                step1 = submitted + timedelta(days=rng.randint(0, 2), hours=rng.randint(2, 20))
                step2 = step1 + timedelta(days=rng.randint(1, 4), hours=rng.randint(0, 6))
                approver2 = staff["hod"] if amount >= 3000 or rng.random() < 0.5 else staff["adviser"]
                request_status = {"paid": "fulfilled", "rejected": "rejected", "withdrawn": "withdrawn",
                                  "approved_unpaid": "approved", "pending_step2": "pending_approval",
                                  "submitted": "submitted"}[outcome]
                decided = {"paid": step2, "approved_unpaid": step2, "rejected": step2,
                           "withdrawn": step1}.get(outcome)
                paid_on = None
                if outcome == "paid":
                    paid_on = max(needed_by - timedelta(days=rng.randint(0, 3)), step2.date())
                updated = at(paid_on, 15) if paid_on else (decided or step1 if outcome != "submitted" else submitted)
                used = [submitted, updated]
                used += [step1] if outcome != "submitted" else []
                used += [step2] if outcome not in ("submitted", "pending_step2", "withdrawn") else []
                assert max(used) <= ctx.as_of, (title, max(used))
                req = ctx.add("expense_requests", submitted - timedelta(hours=1), updated, department_id=dept["id"],
                              budget_id=budget["id"], requested_by_id=execs[requester]["id"], title=title,
                              purpose=purpose, requested_amount=money(amount), currency=config.CURRENCY,
                              needed_by=needed_by, request_status=request_status, submitted_at=submitted,
                              decided_at=decided,
                              decision_note=REJECTION_NOTES.get(outcome) or ("Approved." if decided else None))
                if outcome != "withdrawn":
                    d1 = "pending" if outcome == "submitted" else "approved"
                    ctx.add("expense_approvals", submitted, step1 if d1 != "pending" else submitted,
                            expense_request_id=req["id"], step_number=1, approver_user_id=execs["President"]["id"],
                            decision=d1, comments=None if d1 == "pending" else "Within budget.",
                            due_at=submitted + timedelta(days=3), acted_at=None if d1 == "pending" else step1)
                    if outcome != "submitted":
                        d2 = {"rejected": "rejected", "pending_step2": "pending"}.get(outcome, "approved")
                        ctx.add("expense_approvals", step1, step2 if d2 != "pending" else step1,
                                expense_request_id=req["id"], step_number=2, approver_user_id=approver2["id"],
                                decision=d2, comments=REJECTION_NOTES["rejected"] if d2 == "rejected" else
                                (None if d2 == "pending" else "Approved. Keep receipts for audit."),
                                due_at=step1 + timedelta(days=5), acted_at=step2 if d2 != "pending" else None)
                if outcome in ("paid", "approved_unpaid"):
                    voucher[sidx] += 1
                    year = sess["cfg"]["starts_on"].year % 100
                    if amount >= 3000:
                        account, ref = accounts["bank"], ids.bank_reference(rng, paid_on or needed_by)
                    elif rng.random() < 0.6:
                        account, ref = accounts["mobile_money"], ids.momo_transaction_id(rng)
                    else:
                        account, ref = accounts["cash"], f"PV/CSE/{year}/{voucher[sidx]:03d}"
                    status = "paid" if outcome == "paid" else "pending_payment"
                    ctx.add("expenses", step2, at(paid_on, 15) if paid_on else step2, department_id=dept["id"],
                            expense_request_id=req["id"], financial_account_id=account["id"], vendor_name=vendor,
                            description=title, category=budget["category"], expense_status=status,
                            amount=money(amount if outcome != "paid" else _actual(rng, amount)),
                            currency=config.CURRENCY, incurred_on=needed_by if outcome == "paid" else None,
                            paid_on=paid_on, payment_reference=ref if paid_on else None,
                            recorded_by_id=execs["Treasurer"]["id"],
                            verified_by_id=(execs["Financial Secretary"]["id"] if paid_on else None))

        # Small recurring charges recorded directly, without a request.
        for month_start in _month_starts(sess["cfg"]["starts_on"], min(sess["cfg"]["ends_on"], ctx.as_of.date())):
            paid = month_start + timedelta(days=27)
            if paid > ctx.as_of.date():
                break
            ctx.add("expenses", at(paid, 16), department_id=dept["id"], financial_account_id=accounts["bank"]["id"],
                    vendor_name=None, description="Bank account maintenance fee and SMS alerts",
                    category="Administration", expense_status="paid", amount=money(rng.choice([18, 18, 20, 22])),
                    currency=config.CURRENCY, incurred_on=paid, paid_on=paid, payment_reference=None,
                    recorded_by_id=execs["Treasurer"]["id"])

    ctx.ref["budgets"] = budgets


def _actual(rng, amount):
    """Actual spend lands close to the request, occasionally a little under."""
    return amount if rng.random() < 0.6 else round(amount * rng.uniform(0.9, 1.0) / 5) * 5


def _month_starts(start, end):
    d = date(start.year, start.month, 1)
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
