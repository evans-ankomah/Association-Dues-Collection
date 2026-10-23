"""events, event_registrations, event_attendance, committees, committee_members, meetings, tasks,
service_requests, service_request_comments."""
from datetime import date, datetime, timedelta

from .. import reference
from ..config import UTC
from ..core import OFFICE_HOURS, at, next_weekday, rand_time, weighted_day

V = reference.VENUES

# key, title, type, venue, start, end, capacity, registration_required, budget key, audience, attendance share
EVENTS = {
    0: [
        ("orientation", "Freshers' Orientation 2025", "orientation", V["auditorium"], (2025, 9, 19, 9), (2025, 9, 19, 13),
         200, False, "orientation", [100], 0.86),
        ("hackathon", "CSE Hackathon 2025: Tech for Mining Communities", "hackathon", V["cse_lab"],
         (2025, 11, 14, 9), (2025, 11, 15, 17), 72, True, "hackathon", [200, 300, 400], 0.17),
        ("seminar", "Tech Seminar: AI and Automation in Mining Operations", "seminar", V["auditorium"],
         (2026, 2, 20, 14), (2026, 2, 20, 17), 400, False, None, [100, 200, 300, 400], 0.38),
        ("cse_week", "CSE Week 2026", "departmental_week", "FCMS Block and UMaT Auditorium", (2026, 3, 23, 8),
         (2026, 3, 28, 22), None, False, "cse_week", [100, 200, 300, 400], 0.55),
        ("gala", "CSE Week Inter-level Football Gala", "sports", "UMaT Sports Park", (2026, 3, 25, 15),
         (2026, 3, 25, 18), None, False, "cse_week", [100, 200, 300, 400], 0.3),
        ("visit", "Level 300 Industrial Visit 2026 (Accra)", "excursion", "Accra: technology firms and a data centre",
         (2026, 4, 8, 5), (2026, 4, 10, 20), 70, True, "visit", [300], None),
        ("dinner", "Final Year Dinner & Awards Night 2026", "social", "Riverside Events Centre, Tarkwa",
         (2026, 5, 16, 18), (2026, 5, 16, 23), 90, True, "dinner", [400], None),
    ],
    1: [
        ("orientation", "Freshers' Orientation 2026", "orientation", V["auditorium"], (2026, 9, 25, 9),
         (2026, 9, 25, 13), 200, False, "orientation", [100], 0.88),
        ("bootcamp", "Python Bootcamp for Freshers", "workshop", V["cse_lab"], (2026, 10, 17, 9), (2026, 10, 17, 15),
         60, True, None, [100], 0.48),
        ("career", "Career Talk: Building a Tech Career from Tarkwa", "seminar", V["auditorium"], (2026, 11, 6, 14),
         (2026, 11, 6, 17), 400, False, None, [100, 200, 300, 400], None),
        ("hackathon", "CSE Hackathon 2026: Smart Campus", "hackathon", V["cse_lab"], (2026, 11, 13, 9),
         (2026, 11, 14, 17), 80, True, "hackathon", [200, 300, 400], 0.12),
    ],
}

COMMITTEES = [
    ("Welfare Committee", "Supports members in hardship; recommends dues waivers.", "Women's Commissioner"),
    ("Organising Committee", "Plans orientation, CSE Week, hackathon and social events.", "Organising Secretary"),
    ("Academic Committee", "Tutorials, study groups and liaison with lecturers.", "Vice President"),
    ("Sports Committee", "Inter-level and inter-department sports.", None),
    ("Finance Committee", "Budget preparation and quarterly finance reports.", "Treasurer"),
]

# (day, title, committee name or None, status)
MEETINGS = {
    0: [(date(2025, 8, 27), "Executive meeting: plans for 2025/2026", None, "held"),
        (date(2025, 9, 10), "Orientation planning", "Organising Committee", "held"),
        (date(2025, 9, 24), "Executive meeting: dues drive", None, "held"),
        (date(2025, 10, 22), "Hackathon planning", "Organising Committee", "held"),
        (date(2025, 10, 29), "Executive meeting: dues collection review", None, "held"),
        (date(2025, 11, 5), "Welfare cases and waiver recommendations", "Welfare Committee", "held"),
        (date(2025, 11, 26), "Executive meeting: end-of-semester report", None, "held"),
        (date(2026, 1, 21), "Executive meeting: second semester plans", None, "held"),
        (date(2026, 1, 28), "CSE Week planning", "Organising Committee", "held"),
        (date(2026, 2, 4), "Mid-year budget review", "Finance Committee", "held"),
        (date(2026, 2, 11), "Football gala fixtures", "Sports Committee", "held"),
        (date(2026, 2, 18), "Study groups for second semester", "Academic Committee", "held"),
        (date(2026, 3, 4), "Executive meeting: CSE Week final checks", None, "cancelled"),
        (date(2026, 3, 11), "Executive meeting: CSE Week final checks", None, "held"),
        (date(2026, 4, 15), "Dinner and awards planning", "Organising Committee", "held"),
        (date(2026, 5, 27), "Executive handover meeting", None, "held")],
    1: [(date(2026, 8, 26), "Executive meeting: plans for 2026/2027", None, "held"),
        (date(2026, 9, 9), "Orientation planning", "Organising Committee", "held"),
        (date(2026, 9, 23), "Executive meeting: dues drive", None, "held"),
        (date(2026, 9, 30), "Welfare cases review", "Welfare Committee", "held"),
        (date(2026, 10, 7), "Budget presentation for 2026/2027", "Finance Committee", "held"),
        (date(2026, 10, 14), "Hackathon planning", "Organising Committee", "held"),
        (date(2026, 10, 21), "Executive meeting: dues collection review", None, "held"),
        (date(2026, 10, 28), "Executive meeting: hackathon logistics", None, "scheduled"),
        (date(2026, 11, 4), "Hackathon final checks", "Organising Committee", "scheduled")],
}

# (title template, owner office, days before event the task is due)
EVENT_TASKS = [("Book venue for {e}", "General Secretary", 21), ("Design and share flyers for {e}", "Public Relations Officer", 10),
               ("Confirm refreshments vendor for {e}", "Organising Secretary", 7),
               ("Prepare attendance QR codes for {e}", "General Secretary", 2),
               ("Post photos and short report on {e}", "Public Relations Officer", -3)]

# request_type, title, description, priority, assignee key ('dept_admin','hod','treasurer'), levels, visibility, days to resolve
REQUEST_TYPES = [
    ("introductory_letter", "Introductory letter for industrial attachment",
     "Please issue an introductory letter for industrial attachment during the long vacation.", "normal",
     "dept_admin", [200, 300], "department", (2, 6), 14),
    ("lab_access", "After-hours access to CSE Lab 2 for project work",
     "Requesting evening access to CSE Lab 2 to work on my final-year project.", "normal", "dept_admin", [400],
     "department", (1, 5), 6),
    ("equipment_fault", "Projector in FCMS Lecture Room 4 not working",
     "The projector does not display from the HDMI input. Several lectures affected.", "high", "dept_admin",
     [100, 200, 300, 400], "department", (3, 15), 4),
    ("equipment_fault", "Several PCs in CSE Lab 1 not booting",
     "About six PCs on the back row show a disk error at start-up.", "high", "dept_admin", [100, 200, 300, 400],
     "department", (4, 20), 3),
    ("equipment_fault", "Air conditioner leaking in CSE Lab 2",
     "Water dripping from the AC unit near the window onto the bench.", "normal", "dept_admin",
     [100, 200, 300, 400], "department", (5, 25), 2),
    ("result_query", "Grade missing for a course on the student portal",
     "My grade for one of last semester's courses shows as IC on the portal.", "normal", "hod", [200, 300, 400],
     "restricted", (5, 21), 8),
    ("dues_query", "MoMo payment not reflecting on DeptHub",
     "I paid my dues by MoMo but my balance still shows outstanding.", "high", "treasurer", [100, 200, 300, 400],
     "department", (0, 2), 10),
    ("venue_booking", "Booking FCMS Lecture Room 4 for a study group",
     "Requesting the room on Saturdays 10am-1pm for a study group.", "low", "dept_admin", [200, 300],
     "department", (1, 4), 4),
    ("admin_question", "Question about changing elective course",
     "How do I change an elective after course registration has closed?", "low", "hod", [300, 400], "department",
     (1, 7), 5),
]
REPLIES = {
    "introductory_letter": "Your letter is ready for collection at the departmental office.",
    "lab_access": "Approved for weekdays 5-9pm until the end of semester. Sign the lab register each time.",
    "equipment_fault": "Reported to the works department; technician has fixed the fault.",
    "result_query": "Grade has been corrected after the lecturer resubmitted the marks.",
    "dues_query": "Found the transaction on the MoMo statement and confirmed it. Your receipt has been issued.",
    "venue_booking": "Room booked. Please leave it clean.",
    "admin_question": "See the HoD during office hours with a completed course change form.",
}


def _dt(parts):
    return datetime(*parts, tzinfo=UTC)


def build(ctx):
    rng = ctx.stream("ops")
    events = _events(ctx, rng)
    committees = _committees(ctx, rng)
    meetings = _meetings(ctx, rng, committees)
    _tasks(ctx, rng, events, committees, meetings)
    _service_requests(ctx, rng)


def _events(ctx, rng):
    dept = ctx.ref["dept"]
    out = {}
    paid = {}
    for plan in ctx.ref["assessment_plans"]:
        if plan["outcome"] == "full":
            paid.setdefault((plan["sidx"], plan["cfg"]["key"]), []).append(plan["m"])
    for sidx, items in EVENTS.items():
        execs = ctx.ref["execs"][sidx]
        members = [m for m in ctx.ref["memberships"][sidx] if m["status"] in ("active", "graduated")]
        for key, title, etype, venue, start, end, cap, reg, bkey, levels, share in items:
            starts, ends = _dt(start), _dt(end)
            created = starts - timedelta(days=rng.randint(18, 35))
            if sidx == 1 and key in ("career", "hackathon", "bootcamp"):
                created = min(created, ctx.as_of - timedelta(days=rng.randint(10, 14)))
            if ends < ctx.as_of:
                status = "completed"
            elif key == "career":
                status = "pending_approval"
            else:
                status = "published"
            published = created + timedelta(days=rng.randint(1, 3)) if status != "pending_approval" else None
            budget = ctx.ref["budgets"].get((sidx, bkey)) if bkey else None
            ev = ctx.add("events", created, min(ends + timedelta(days=1), ctx.as_of), department_id=dept["id"],
                         title=title, description=f"{title}. Organised by the CSE Students' Association.",
                         event_type=etype, venue_text=venue, starts_at=starts, ends_at=ends, capacity=cap,
                         registration_required=reg, event_status=status, created_by_id=execs["Organising Secretary"]["id"],
                         approved_by_id=ctx.ref["staff"]["adviser"]["id"] if published else None,
                         published_at=published, related_budget_id=budget["id"] if budget else None)
            out[(sidx, key)] = ev
            eligible = [m for m in members if m["level"] in levels]
            if key in ("visit", "dinner"):
                attendees = paid.get((sidx, key), [])
            else:
                attendees = rng.sample(eligible, min(len(eligible), int(len(eligible) * share))) if share else []
            regs = {}
            if reg:
                open_at = published or created
                close = min(starts - timedelta(hours=12), ctx.as_of)
                for m in (attendees if status == "completed" else
                          rng.sample(eligible, min(len(eligible), int((cap or 60) * 0.65)))):
                    when = weighted_day(rng, open_at.date(), close.date(), lambda d: 1.0)
                    when = min(max(rand_time(rng, when, (8, 22)), open_at, m["joined_at"]), close)
                    regs[m["row"]["id"]] = ctx.add("event_registrations", when, department_membership_id=m["row"]["id"],
                                                   event_id=ev["id"], registration_status="registered",
                                                   registered_at=when)
                # A few cancellations and a waitlist for capped events.
                extra = [m for m in eligible if m["row"]["id"] not in regs]
                for m in rng.sample(extra, min(len(extra), 4)):
                    when = min(max(rand_time(rng, open_at.date() + timedelta(days=2), (8, 22)), m["joined_at"]), close)
                    cancelled = min(when + timedelta(days=rng.randint(1, 6)), close)
                    ctx.add("event_registrations", when, cancelled, event_id=ev["id"],
                            department_membership_id=m["row"]["id"], registration_status="cancelled",
                            registered_at=when, cancelled_at=cancelled, notes="Clash with lab session.")
            if status != "completed":
                continue
            checker = execs["General Secretary"]
            for m in attendees:
                late = rng.random() < 0.12
                t = starts + timedelta(minutes=rng.randint(30, 75) if late else rng.randint(-25, 20))
                ctx.add("event_attendance", t, event_id=ev["id"], department_membership_id=m["row"]["id"],
                        attendance_status="late" if late else "present", checked_in_at=t,
                        checked_in_by_id=checker["id"], checkin_method="qr" if rng.random() < 0.8 else "manual")
                if m["row"]["id"] in regs:
                    regs[m["row"]["id"]]["registration_status"] = "attended"
                    regs[m["row"]["id"]]["updated_at"] = t
            for r in regs.values():
                if r["registration_status"] == "registered":
                    r["registration_status"], r["updated_at"] = "no_show", ends
    return out


def _committees(ctx, rng):
    dept = ctx.ref["dept"]
    sessions = ctx.ref["sessions"]
    out = {}
    for sidx, sess in enumerate(sessions):
        execs, exec_m = ctx.ref["execs"][sidx], ctx.ref["exec_memberships"][sidx]
        closed = sess["cfg"]["status"] == "closed"
        start = at(sess["cfg"]["starts_on"] + timedelta(days=3), 16)
        end = at(sessions[-1]["cfg"]["starts_on"], 7) if closed else None
        pool = [m for m in ctx.ref["memberships"][sidx]
                if m["level"] in (200, 300, 400) and m["status"] in ("active", "graduated")
                and m["row"]["id"] not in {x["row"]["id"] for x in exec_m.values()}]
        for name, desc, chair_office in COMMITTEES:
            chair = exec_m[chair_office] if chair_office else rng.choice(pool)
            c = ctx.add("committees", start, end or start, department_id=dept["id"],
                        academic_session_id=sess["row"]["id"], name=name, description=desc,
                        chair_membership_id=chair["row"]["id"], committee_status="archived" if closed else "active",
                        created_by_id=execs["General Secretary"]["id"])
            out[(sidx, name)] = c
            members = [chair] + rng.sample([m for m in pool if m is not chair], rng.randint(4, 7))
            for i, m in enumerate(members):
                joined = max(start, m["joined_at"]) + timedelta(hours=i)
                ctx.add("committee_members", joined, end or joined, committee_id=c["id"],
                        department_membership_id=m["row"]["id"],
                        role_title="Chair" if i == 0 else ("Secretary" if i == 1 else "Member"), joined_at=joined,
                        left_at=end, membership_status="ended" if closed else "active")
    return out


def _meetings(ctx, rng, committees):
    dept = ctx.ref["dept"]
    out = {}
    for sidx, items in MEETINGS.items():
        execs = ctx.ref["execs"][sidx]
        for day, title, cname, status in items:
            when = at(day, 16)
            created = min(when - timedelta(days=rng.randint(3, 7)), ctx.as_of - timedelta(hours=3))
            updated = when + timedelta(hours=2) if status == "held" else created
            out[(sidx, day)] = ctx.add(
                "meetings", created, updated, department_id=dept["id"],
                committee_id=committees[(sidx, cname)]["id"] if cname else None, title=title, scheduled_at=when,
                location_text=reference.VENUES["dept_office"] if cname is None else reference.VENUES["fcms_room"],
                meeting_status=status, created_by_id=execs["General Secretary"]["id"])
    return out


def _tasks(ctx, rng, events, committees, meetings):
    dept = ctx.ref["dept"]
    for (sidx, key), ev in events.items():
        if key in ("gala", "career"):
            continue
        execs, exec_m = ctx.ref["execs"][sidx], ctx.ref["exec_memberships"][sidx]
        organising = committees[(sidx, "Organising Committee")]
        for template, office, days_before in EVENT_TASKS:
            due = ev["starts_at"] - timedelta(days=days_before)
            created = min(ev["created_at"] + timedelta(days=rng.randint(0, 3)), ctx.as_of - timedelta(hours=1))
            if due < ctx.as_of:
                status = "done" if rng.random() < 0.93 else "cancelled"
                completed = due - timedelta(hours=rng.randint(2, 72)) if status == "done" else None
                completed = max(completed, created + timedelta(hours=1)) if completed else None
            else:
                status = rng.choice(["todo", "in_progress", "in_progress", "blocked"])
                completed = None
            ctx.add("tasks", created, completed or created, department_id=dept["id"],
                    title=template.format(e=ev["title"]), task_status=status,
                    priority="high" if days_before <= 2 else "normal", assigned_to_user_id=execs[office]["id"],
                    assigned_membership_id=exec_m[office]["row"]["id"], committee_id=organising["id"],
                    event_id=ev["id"], created_by_id=execs["President"]["id"], due_at=due, completed_at=completed)
    # Action items from finance/dues review meetings.
    for (sidx, day), mt in meetings.items():
        if "dues" not in mt["title"] or mt["meeting_status"] != "held":
            continue
        execs, exec_m = ctx.ref["execs"][sidx], ctx.ref["exec_memberships"][sidx]
        for title, office in (("Send dues reminders to Level class reps", "Financial Secretary"),
                              ("Reconcile MoMo statement with DeptHub payments", "Treasurer")):
            created = mt["scheduled_at"] + timedelta(hours=2)
            due = created + timedelta(days=5)
            done = due < ctx.as_of
            completed = due - timedelta(days=rng.randint(1, 3)) if done else None
            ctx.add("tasks", created, completed or created, department_id=dept["id"], title=title,
                    task_status="done" if done else "in_progress", priority="high",
                    assigned_to_user_id=execs[office]["id"], assigned_membership_id=exec_m[office]["row"]["id"],
                    meeting_id=mt["id"], created_by_id=execs["General Secretary"]["id"], due_at=due,
                    completed_at=completed)


def _service_requests(ctx, rng):
    dept = ctx.ref["dept"]
    staff = ctx.ref["staff"]
    sessions = ctx.ref["sessions"]
    for sidx, sess in enumerate(sessions):
        execs = ctx.ref["execs"][sidx]
        members = [m for m in ctx.ref["memberships"][sidx] if m["status"] in ("active", "graduated")]
        start = sess["cfg"]["starts_on"] + timedelta(days=7)
        end = sess["cfg"]["sem2"][1] if sidx == 0 else ctx.as_of.date() - timedelta(days=1)
        for rtype, title, desc, priority, assignee_key, levels, visibility, (lo, hi), count in REQUEST_TYPES:
            n = count if sidx == 0 else max(1, count // 3)
            for _ in range(n):
                m = rng.choice([x for x in members if x["level"] in levels])
                if rtype == "introductory_letter" and sidx == 0:
                    day = weighted_day(rng, date(2026, 4, 1), date(2026, 6, 5), lambda d: 1.0)
                else:
                    day = weighted_day(rng, start, end, lambda d: 0.3 if d.weekday() >= 5 else 1.0)
                submitted = max(rand_time(rng, day, (7, 23)), m["joined_at"] + timedelta(hours=1))
                if submitted > ctx.as_of - timedelta(hours=2):
                    continue
                assignee = execs["Treasurer"] if assignee_key == "treasurer" else staff[assignee_key]
                triaged = next_weekday((submitted + timedelta(hours=rng.randint(2, 30))).date())
                triaged = rand_time(rng, triaged, OFFICE_HOURS)
                resolve = rand_time(rng, next_weekday(triaged.date() + timedelta(days=rng.randint(lo, hi))),
                                    OFFICE_HOURS)
                rejected = rtype == "lab_access" and rng.random() < 0.15
                if resolve <= ctx.as_of:
                    status = "closed" if sidx == 0 or rng.random() < 0.5 else "resolved"
                    if rejected:
                        status = "rejected"
                    resolved_at, summary = resolve, ("Lab access is limited to project groups with supervisor "
                                                     "approval." if rejected else REPLIES[rtype])
                else:
                    status = rng.choice(["triaged", "in_progress", "waiting"]) if triaged <= ctx.as_of else "submitted"
                    resolved_at, summary = None, None
                sr = ctx.add("service_requests", submitted, min(resolved_at or triaged, ctx.as_of),
                             department_id=dept["id"], requester_membership_id=m["row"]["id"], request_type=rtype,
                             title=title, description=desc, priority=priority, request_status=status,
                             assigned_to_user_id=assignee["id"] if status != "submitted" else None,
                             submitted_at=submitted, due_at=submitted + timedelta(days=hi),
                             resolved_at=resolved_at, resolution_summary=summary, visibility_level=visibility)
                if triaged <= ctx.as_of and status != "submitted":
                    ctx.add("service_request_comments", triaged, service_request_id=sr["id"],
                            author_user_id=assignee["id"], body="Received - we are looking into this.",
                            visibility="requester_visible")
                    if rtype == "equipment_fault":
                        ctx.add("service_request_comments", triaged + timedelta(minutes=10), service_request_id=sr["id"],
                                author_user_id=assignee["id"], body="Logged with the works department (job card raised).",
                                visibility="staff_only")
                if resolved_at:
                    ctx.add("service_request_comments", resolved_at, service_request_id=sr["id"],
                            author_user_id=assignee["id"], body=summary, visibility="requester_visible")
                    if rng.random() < 0.4:
                        t = min(resolved_at + timedelta(hours=rng.randint(1, 20)), ctx.as_of)
                        ctx.add("service_request_comments", t, service_request_id=sr["id"],
                                author_user_id=m["user"]["id"], body="Thank you!", visibility="requester_visible")
