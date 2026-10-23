"""The system role and permission catalogue (workbook "Roles & Access" sheet, matching the seed data).

Kept as plain data so migrations can import it safely. `sync_catalog` applies it idempotently.
"""

PERMISSIONS = [
    # (code, module_key, action_key, description)
    ("profile.own.view", "profile", "view", "View own profile and memberships."),
    ("members.roster.view", "members", "view", "View department roster."),
    ("members.roster.edit", "members", "edit", "Add, verify and update department memberships."),
    ("dues.own.view", "dues", "view", "View own assessments and balance."),
    ("dues.assessment.create", "dues", "create", "Create dues types and assessments."),
    ("dues.waiver.approve", "dues", "approve", "Approve dues waivers."),
    ("finance.payment.initiate", "finance", "create", "Initiate an online payment for own assessments."),
    ("finance.payment.record", "finance", "create", "Record an offline (cash/bank/MoMo) payment."),
    ("finance.payment.verify", "finance", "approve", "Verify and confirm recorded payments."),
    ("finance.receipt.view", "finance", "view", "View receipts within scope."),
    ("finance.reconciliation.view", "finance", "view", "View reconciliation queues and provider events."),
    ("finance.budget.create", "finance", "create", "Prepare budgets."),
    ("finance.budget.approve", "finance", "approve", "Approve budgets."),
    ("finance.expense.create", "finance", "create", "Raise expense requests and record expenses."),
    ("finance.expense.approve", "finance", "approve", "Approve expense requests."),
    ("finance.adjustment.approve", "finance", "approve", "Approve refunds, reversals and corrections."),
    ("finance.report.export", "finance", "export", "Export finance reports."),
    ("announcements.view", "announcements", "view", "Read published notices."),
    ("announcements.publish", "announcements", "create", "Draft and publish notices."),
    ("events.register", "events", "create", "Register for events."),
    ("events.manage", "events", "edit", "Create and manage events and attendance."),
    ("requests.create", "requests", "create", "Submit service requests."),
    ("requests.manage", "requests", "edit", "Triage and resolve service requests."),
    ("committees.manage", "committees", "edit", "Manage committees, meetings and tasks."),
    ("assets.manage", "assets", "edit", "Maintain assets and approve bookings."),
    ("collaboration.respond", "collaboration", "approve", "Accept or decline collaboration invitations."),
    ("audit.view", "audit", "view", "Read audit records."),
    ("platform.config.manage", "platform", "edit", "Manage platform configuration."),
]

MEMBER_BASE = [
    "profile.own.view",
    "dues.own.view",
    "finance.payment.initiate",
    "finance.receipt.view",
    "announcements.view",
    "events.register",
    "requests.create",
]

ROLES = [
    # (code, name, scope_type, description, is_system_role, permission codes)
    (
        "student_member",
        "Student / Member",
        "department",
        "Department member: own profile, dues, receipts, notices, events and requests.",
        True,
        MEMBER_BASE,
    ),
    (
        "financial_secretary",
        "Financial Secretary",
        "department",
        "Creates dues assessments and records permitted offline payments.",
        True,
        MEMBER_BASE
        + [
            "dues.assessment.create",
            "finance.payment.record",
            "finance.reconciliation.view",
            "members.roster.view",
        ],
    ),
    (
        "treasurer",
        "Treasurer",
        "department",
        "Reviews finance, reconciles accounts, prepares budgets and expenses.",
        True,
        MEMBER_BASE
        + [
            "finance.payment.verify",
            "finance.reconciliation.view",
            "finance.budget.create",
            "finance.expense.create",
            "finance.report.export",
            "members.roster.view",
        ],
    ),
    (
        "department_secretary",
        "Department Secretary",
        "department",
        "Manages roster, notices and minutes.",
        True,
        MEMBER_BASE
        + ["announcements.publish", "committees.manage", "members.roster.view", "members.roster.edit"],
    ),
    (
        "department_president",
        "Department President / Executive Lead",
        "department",
        "Manages activities, assigns tasks, approves within delegated authority.",
        True,
        MEMBER_BASE
        + [
            "announcements.publish",
            "committees.manage",
            "events.manage",
            "finance.expense.approve",
            "members.roster.view",
            "requests.manage",
        ],
    ),
    (
        "hod_faculty_adviser",
        "HoD / Faculty Adviser",
        "department",
        "Oversight: reviews and approves assigned reports and workflows.",
        True,
        [
            "profile.own.view",
            "audit.view",
            "dues.waiver.approve",
            "finance.adjustment.approve",
            "finance.budget.approve",
            "finance.expense.approve",
            "finance.report.export",
            "members.roster.view",
            "requests.manage",
        ],
    ),
    (
        "partner_department_rep",
        "Partner Department Representative",
        "department",
        "Responds to collaboration invitations for their department.",
        True,
        ["profile.own.view", "collaboration.respond"],
    ),
    (
        "asset_custodian",
        "Asset Custodian",
        "department",
        "Maintains inventory and approves resource bookings.",
        True,
        ["profile.own.view", "assets.manage", "requests.manage"],
    ),
    (
        "platform_admin",
        "Platform Administrator",
        "platform",
        "Technical administration and account recovery.",
        True,
        ["profile.own.view", "audit.view", "members.roster.edit", "platform.config.manage"],
    ),
    (
        "auditor",
        "Auditor / Read-only Reviewer",
        "department",
        "Reads authorised reports and audit records.",
        True,
        ["profile.own.view", "audit.view", "finance.reconciliation.view", "finance.report.export"],
    ),
    (
        "executive_officer",
        "Executive Officer",
        "department",
        "Custom role for other elected officers (VP, Organising Secretary, Women's Commissioner, PRO).",
        False,
        MEMBER_BASE + ["committees.manage", "events.manage", "members.roster.view"],
    ),
]


def sync_catalog(Role, Permission, RolePermission):
    """Create or update system roles, permissions and grants. Safe to run repeatedly.

    Takes model classes so it works both in migrations (historical models) and at runtime.
    """
    permissions = {}
    for code, module_key, action_key, description in PERMISSIONS:
        permissions[code], _ = Permission.objects.update_or_create(
            permission_code=code,
            defaults={"module_key": module_key, "action_key": action_key, "description": description},
        )
    for code, name, scope_type, description, is_system, codes in ROLES:
        role, _ = Role.objects.update_or_create(
            role_code=code,
            defaults={
                "name": name,
                "scope_type": scope_type,
                "description": description,
                "is_system_role": is_system,
            },
        )
        for perm_code in codes:
            RolePermission.objects.get_or_create(role=role, permission=permissions[perm_code])
