"""UMaT organisational reference data and DeptHub role/permission catalogue.

Faculty/department structure follows UMaT's published structure (Wikipedia listing, checked Oct 2026).
Staff and vendor names are fictitious.
"""

INSTITUTION = {
    "name": "University of Mines and Technology",
    "country_code": "GH",
}

# (code, name, [(dept code, dept name, short name)])
FACULTIES = [
    ("FCMS", "Faculty of Computing and Mathematical Sciences", [
        ("CSE", "Department of Computer Science and Engineering", "Computer Science & Engineering"),
        ("MATH", "Department of Mathematics", "Mathematics"),
    ]),
    ("FOE", "Faculty of Engineering", [
        ("EEE", "Department of Electrical and Electronic Engineering", "Electrical & Electronic"),
        ("MECH", "Department of Mechanical Engineering", "Mechanical Engineering"),
        ("REE", "Department of Renewable Energy Engineering", "Renewable Energy"),
    ]),
    ("FMRT", "Faculty of Mineral Resources Technology", [
        ("MNE", "Department of Mining Engineering", "Mining Engineering"),
        ("MRE", "Department of Minerals Engineering", "Minerals Engineering"),
    ]),
    ("FGES", "Faculty of Geosciences and Environmental Studies", [
        ("GLE", "Department of Geological Engineering", "Geological Engineering"),
        ("GME", "Department of Geomatic Engineering", "Geomatic Engineering"),
        ("ESE", "Department of Environmental and Safety Engineering", "Environmental & Safety"),
    ]),
    ("FIMS", "Faculty of Integrated Management Science", [
        ("TCOM", "Department of Technical Communication", "Technical Communication"),
        ("MGT", "Department of Management Studies", "Management Studies"),
    ]),
    ("SPETS", "School of Petroleum Studies", [
        ("PE", "Department of Petroleum Engineering", "Petroleum Engineering"),
        ("PGE", "Department of Petroleum Geosciences and Engineering", "Petroleum Geosciences"),
        ("CPE", "Department of Chemical and Petrochemical Engineering", "Chemical & Petrochemical"),
    ]),
    ("SRID", "School of Railways and Infrastructure Development (Essikado)", []),
]

# Staff users (fictitious). key -> (title, given, family, role codes, department code for scope)
STAFF = {
    "hod": ("Dr.", "Kwabena", "Asiedu-Mensah", ["hod_faculty_adviser"], "CSE"),
    "adviser": ("Dr.", "Esi", "Quansah", ["hod_faculty_adviser"], "CSE"),
    "dept_admin": ("Mrs.", "Gifty", "Arthur", ["asset_custodian"], "CSE"),
    "platform_admin": ("Mr.", "Isaac", "Ofori-Atta", ["platform_admin"], None),
    "auditor": ("Mr.", "Bernard", "Koomson", ["auditor"], "CSE"),
    "math_rep": ("Dr.", "Abdul-Rahman", "Iddrisu", ["partner_department_rep"], "MATH"),
    "gme_rep": ("Dr.", "Selorm", "Agbenyega", ["partner_department_rep"], "GME"),
}

# Student executive offices -> DeptHub role code. Levels the office holder is drawn from.
EXEC_OFFICES = [
    ("President", "department_president", 400),
    ("General Secretary", "department_secretary", 400),
    ("Financial Secretary", "financial_secretary", 400),
    ("Treasurer", "treasurer", 400),
    ("Vice President", "executive_officer", 300),
    ("Organising Secretary", "executive_officer", 300),
    ("Women's Commissioner", "executive_officer", 300),
    ("Public Relations Officer", "executive_officer", 300),
]

# role_code, name, scope_type, is_system_role, description
ROLES = [
    ("student_member", "Student / Member", "department", True, "Department member: own profile, dues, receipts, notices, events and requests."),
    ("financial_secretary", "Financial Secretary", "department", True, "Creates dues assessments and records permitted offline payments."),
    ("treasurer", "Treasurer", "department", True, "Reviews finance, reconciles accounts, prepares budgets and expenses."),
    ("department_secretary", "Department Secretary", "department", True, "Manages roster, notices and minutes."),
    ("department_president", "Department President / Executive Lead", "department", True, "Manages activities, assigns tasks, approves within delegated authority."),
    ("hod_faculty_adviser", "HoD / Faculty Adviser", "department", True, "Oversight: reviews and approves assigned reports and workflows."),
    ("partner_department_rep", "Partner Department Representative", "department", True, "Responds to collaboration invitations for their department."),
    ("asset_custodian", "Asset Custodian", "department", True, "Maintains inventory and approves resource bookings."),
    ("platform_admin", "Platform Administrator", "platform", True, "Technical administration and account recovery."),
    ("auditor", "Auditor / Read-only Reviewer", "department", True, "Reads authorised reports and audit records."),
    ("executive_officer", "Executive Officer", "department", False, "Custom role for other elected officers (VP, Organising Secretary, Women's Commissioner, PRO)."),
]

# permission_code, module_key, action_key, description
PERMISSIONS = [
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

_MEMBER = ["profile.own.view", "dues.own.view", "finance.payment.initiate", "finance.receipt.view",
           "announcements.view", "events.register", "requests.create"]
ROLE_PERMISSIONS = {
    "student_member": _MEMBER,
    "financial_secretary": _MEMBER + ["members.roster.view", "dues.assessment.create", "finance.payment.record",
                                      "finance.reconciliation.view"],
    "treasurer": _MEMBER + ["members.roster.view", "finance.payment.verify", "finance.reconciliation.view",
                            "finance.budget.create", "finance.expense.create", "finance.report.export"],
    "department_secretary": _MEMBER + ["members.roster.view", "members.roster.edit", "announcements.publish",
                                       "committees.manage"],
    "department_president": _MEMBER + ["members.roster.view", "announcements.publish", "events.manage",
                                       "committees.manage", "finance.expense.approve", "requests.manage"],
    "hod_faculty_adviser": ["profile.own.view", "members.roster.view", "dues.waiver.approve", "finance.budget.approve",
                            "finance.expense.approve", "finance.adjustment.approve", "finance.report.export",
                            "requests.manage", "audit.view"],
    "partner_department_rep": ["profile.own.view", "collaboration.respond"],
    "asset_custodian": ["profile.own.view", "assets.manage", "requests.manage"],
    "platform_admin": ["profile.own.view", "platform.config.manage", "members.roster.edit", "audit.view"],
    "auditor": ["profile.own.view", "finance.reconciliation.view", "finance.report.export", "audit.view"],
    "executive_officer": _MEMBER + ["members.roster.view", "events.manage", "committees.manage"],
}

VENUES = {
    "auditorium": "UMaT Auditorium, Main Campus, Tarkwa",
    "cse_lab": "CSE Computer Laboratory 1, FCMS Block",
    "cse_lab2": "CSE Computer Laboratory 2, FCMS Block",
    "fcms_room": "FCMS Lecture Room 4",
    "library": "University Library Seminar Room",
    "dept_office": "CSE Departmental Office, FCMS Block",
    "com_hall": "Chamber of Mines Hall Forecourt",
}

# Ghanaian banks with a Tarkwa presence, for bank transfers and the association account.
BANKS = ["GCB Bank", "Ecobank Ghana", "CalBank", "Fidelity Bank", "Absa Bank Ghana"]
ASSOCIATION_BANK = "CalBank"
