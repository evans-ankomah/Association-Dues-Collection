"""Tunable settings for the UMaT sample dataset.

Everything that shapes volume, money or timing lives here so the builders stay free of magic numbers.
Amounts and rates are illustrative: no published UMaT departmental dues schedule exists.
"""
from datetime import date, datetime, timezone

UTC = timezone.utc

SEED = 2026
# Snapshot moment. No created/confirmed/paid timestamp is generated after this.
AS_OF = datetime(2026, 10, 22, 15, 0, 0, tzinfo=UTC)
# Platform onboarding, just before the 2025/2026 session.
PLATFORM_LAUNCH = datetime(2025, 8, 11, 9, 0, 0, tzinfo=UTC)

CURRENCY = "GHS"
TIMEZONE = "Africa/Accra"  # UTC+0, no DST, so local time == UTC

# Non-routable domains so generated users can never receive real email.
STUDENT_EMAIL_DOMAIN = "st.umat.test"
STAFF_EMAIL_DOMAIN = "umat.test"

FOCUS_DEPARTMENT_CODE = "CSE"
PROGRAMME_NAME = "BSc Computer Science and Engineering"
# Real UMaT student-ID format is not public; this pattern is an assumption.
STUDENT_NUMBER_PREFIX = "CE"
STUDENT_NUMBER_PATTERN = "{prefix}-{entry_year}-{serial:04d}"

SESSIONS = [
    {
        "name": "2025/2026",
        "starts_on": date(2025, 8, 25),
        "ends_on": date(2026, 7, 31),
        "status": "closed",
        "is_current": False,
        "sem1": (date(2025, 8, 25), date(2025, 12, 12)),
        "sem2": (date(2026, 1, 19), date(2026, 6, 5)),
        "level_sizes": {100: 110, 200: 105, 300: 100, 400: 95},
    },
    {
        "name": "2026/2027",
        "starts_on": date(2026, 8, 24),
        "ends_on": date(2027, 7, 30),
        "status": "active",
        "is_current": True,
        "sem1": (date(2026, 8, 24), date(2026, 12, 11)),
        "sem2": (date(2027, 1, 18), date(2027, 6, 4)),
        # Continuing levels are derived from last session minus attrition; only the new intake is set.
        "new_intake": 115,
    },
]
# Students in each 2025/26 cohort (keyed by 2025/26 level) who do not continue into 2026/27.
ATTRITION = {100: 2, 200: 3, 300: 2}
# Current-session members who are inactive or suspended (not counting attrition above).
CURRENT_INACTIVE = 3
CURRENT_SUSPENDED = 1

FEMALE_SHARE = 0.25

# Payment-method mix (student preference). Paystack is recorded as payment_method="provider".
METHOD_WEIGHTS = {"mobile_money": 65, "provider": 15, "cash": 15, "bank_transfer": 5}
# Ghana mobile networks: (wallet name, prefixes, weight).
NETWORKS = [
    ("MTN MoMo", ["24", "54", "55", "59", "53", "25"], 60),
    ("Telecel Cash", ["20", "50"], 25),
    ("AT Money", ["26", "56", "27", "57"], 15),
]

# Dues per session. "levels" None means all levels.
# outcome rates are shares of eligible assessments: full / partial / waived / (rest outstanding)
DUES_TYPES = {
    "2025/2026": [
        {
            "key": "dues", "name": "Departmental Dues 2025/2026", "category": "departmental_dues",
            "amount": 120, "mandatory": True, "levels": None, "status": "closed",
            "created_on": date(2025, 8, 29), "due_date": date(2025, 10, 17),
            "pay_window_end": date(2026, 5, 29),
            "description": "Annual CSE Students' Association dues covering welfare, orientation, CSE Week and departmental activities.",
            "eligibility": "All active CSE students, Levels 100-400.",
            "rates": {"full": 0.78, "partial": 0.08, "waived": 0.03},
        },
        {
            "key": "souvenir", "name": "CSE Week 2026 Souvenir T-shirt", "category": "souvenir",
            "amount": 90, "mandatory": False, "levels": None, "status": "closed", "opt_in": 0.55,
            "created_on": date(2026, 1, 26), "due_date": date(2026, 2, 27),
            "pay_window_end": date(2026, 3, 6),
            "description": "Branded CSE Week T-shirt (pre-order). Sizes S-XXL.",
            "eligibility": "Optional for all CSE students; assessed on order.",
            "rates": {"full": 0.93, "partial": 0.03, "waived": 0.0},
        },
        {
            "key": "visit", "name": "Level 300 Industrial Visit 2026", "category": "excursion",
            "amount": 350, "mandatory": False, "levels": [300], "status": "closed", "opt_in": 0.72,
            "created_on": date(2026, 2, 2), "due_date": date(2026, 3, 13),
            "pay_window_end": date(2026, 3, 27),
            "description": "Transport, accommodation and feeding for the Level 300 industrial visit.",
            "eligibility": "Level 300 students who register for the trip.",
            "rates": {"full": 0.92, "partial": 0.05, "waived": 0.0},
        },
        {
            "key": "dinner", "name": "Final Year Dinner & Awards Night 2026", "category": "dinner",
            "amount": 200, "mandatory": False, "levels": [400], "status": "closed", "opt_in": 0.68,
            "created_on": date(2026, 3, 9), "due_date": date(2026, 4, 24),
            "pay_window_end": date(2026, 5, 8),
            "description": "Ticket for the Level 400 dinner, awards and send-off.",
            "eligibility": "Level 400 students who opt in.",
            "rates": {"full": 0.94, "partial": 0.03, "waived": 0.0},
        },
    ],
    "2026/2027": [
        {
            "key": "dues", "name": "Departmental Dues 2026/2027", "category": "departmental_dues",
            "amount": 150, "mandatory": True, "levels": None, "status": "active",
            "created_on": date(2026, 8, 28), "due_date": date(2026, 10, 30),
            "pay_window_end": None,
            "description": "Annual CSE Students' Association dues covering welfare, orientation, CSE Week and departmental activities.",
            "eligibility": "All active CSE students, Levels 100-400.",
            "rates": {"full": 0.47, "partial": 0.07, "waived": 0.01},
        },
        {
            "key": "orientation", "name": "Freshers' Orientation Pack 2026", "category": "orientation",
            "amount": 60, "mandatory": True, "levels": [100], "status": "active",
            "created_on": date(2026, 9, 4), "due_date": date(2026, 10, 9),
            "pay_window_end": None,
            "description": "Freshers' handbook, lanyard, ID card holder and orientation refreshments.",
            "eligibility": "All Level 100 CSE students.",
            "rates": {"full": 0.80, "partial": 0.04, "waived": 0.0},
        },
        {
            "key": "souvenir", "name": "CSE Week 2027 Souvenir T-shirt (pre-order)", "category": "souvenir",
            "amount": 100, "mandatory": False, "levels": None, "status": "active", "opt_in": 0.18,
            "created_on": date(2026, 10, 5), "due_date": date(2027, 2, 26),
            "pay_window_end": None,
            "description": "Early-bird pre-order for the CSE Week 2027 T-shirt.",
            "eligibility": "Optional for all CSE students; assessed on order.",
            "rates": {"full": 0.55, "partial": 0.10, "waived": 0.0},
        },
    ],
}
# Payment likelihood shifts by level (freshers pay most reliably).
LEVEL_PAY_ADJUST = {100: 0.06, 200: 0.01, 300: -0.02, 400: -0.05}
INSTALMENT_SHARE = 0.12       # full payers who split into two payments
BUNDLE_SHARE = 0.5            # intents a few days apart that get paid in one transaction
FAILED_ATTEMPT_SHARE = 0.03   # MoMo/Paystack payments preceded by a failed attempt
ABANDONED_CHECKOUT_SHARE = 0.10  # Paystack payments preceded by an abandoned checkout
DUPLICATE_REFUNDS = 3         # duplicate MoMo payments later refunded in full
OVERPAYMENT_REFUNDS = 1       # overpayments partly refunded

WAIVER_REASONS = [
    "Financial hardship - approved by Head of Department after welfare committee review.",
    "Bereavement in the immediate family - welfare waiver.",
    "Student on approved medical leave for most of the semester.",
    "Needy student support (welfare committee recommendation).",
]
PARTIAL_WAIVER_REASON = "Partial welfare waiver (50%) - documented financial hardship."
