"""announcements and notifications."""
from datetime import date, timedelta

from ..core import at, rand_time

# (published date, hour, title, body, audience_type, audience_filter, priority, author office, expires after days)
ANNOUNCEMENTS = {
    0: [
        (date(2025, 8, 26), 9, "Welcome back to the 2025/2026 academic year",
         "Akwaaba back to campus! The CSE Students' Association is now on DeptHub. Log in to confirm your membership, "
         "check your dues and get department notices in one place.", "all_members", None, "normal", "President", 30),
        (date(2025, 8, 29), 12, "Departmental dues 2025/2026 now open - GHS 120",
         "Departmental dues for 2025/2026 are GHS 120.00, payable by 17 October 2025. Pay with MoMo, Paystack or cash "
         "at the departmental office. Receipts are issued automatically once payment is confirmed.",
         "all_members", None, "important", "Financial Secretary", 50),
        (date(2025, 9, 15), 10, "Freshers' orientation - Friday 19 September",
         "All Level 100 students are invited to the CSE freshers' orientation at the UMaT Auditorium, 9:00 am. "
         "Meet your lecturers, executives and the HoD.", "selected_levels", {"levels": ["Level 100"]}, "important",
         "Organising Secretary", 5),
        (date(2025, 10, 10), 8, "Dues deadline: one week left",
         "Reminder: departmental dues close on Friday 17 October. Members with outstanding dues will not be "
         "eligible for subsidised department events.", "all_members", None, "urgent", "Financial Secretary", 8),
        (date(2025, 10, 27), 18, "CSE Hackathon 2025 - team registration open",
         "Form teams of 3-4 and register on DeptHub by 7 November. Theme: Tech for Mining Communities. "
         "Prizes for the top three teams.", "all_members", None, "normal", "President", 12),
        (date(2025, 11, 24), 11, "First semester examination timetable released",
         "The first semester examination timetable is out. Check the notice board at the FCMS Block and the student "
         "portal. Report clashes to the department by Friday.", "all_members", None, "important",
         "General Secretary", 25),
        (date(2026, 1, 20), 9, "Welcome to the second semester",
         "Welcome back. Course registration closes on 6 February. Watch this space for CSE Week 2026 updates.",
         "all_members", None, "normal", "President", 20),
        (date(2026, 1, 26), 17, "CSE Week 2026 T-shirt pre-orders open",
         "Order your CSE Week 2026 souvenir T-shirt (GHS 90) on DeptHub by 27 February. Sizes S-XXL.",
         "all_members", None, "normal", "Public Relations Officer", 32),
        (date(2026, 2, 2), 10, "Level 300 industrial visit - registration and payment",
         "Level 300 students: the industrial visit to Accra runs 8-10 April. Cost is GHS 350 (transport, "
         "accommodation and feeding). Register and pay by 13 March.", "selected_levels", {"levels": ["Level 300"]},
         "important", "Vice President", 40),
        (date(2026, 2, 16), 12, "Tech seminar: AI and automation in mining operations",
         "Join us on Friday 20 February, 2:00 pm, UMaT Auditorium, for a seminar on AI and automation in mining.",
         "all_members", None, "normal", "General Secretary", 5),
        (date(2026, 3, 9), 15, "Final Year Dinner & Awards Night - tickets on sale",
         "Level 400: dinner tickets are GHS 200, payable by 24 April. The dinner is on Saturday 16 May.",
         "selected_levels", {"levels": ["Level 400"]}, "normal", "Organising Secretary", 46),
        (date(2026, 3, 16), 9, "CSE Week 2026 programme",
         "CSE Week runs 23-28 March: exhibition day, football gala, tech quiz and closing night. Full programme on "
         "the events page.", "all_members", None, "important", "President", 14),
        (date(2026, 4, 27), 10, "Second semester examinations - conduct reminder",
         "Examinations begin on 11 May. Phones and smart watches are not allowed in examination halls.",
         "all_members", None, "important", "General Secretary", 40),
        (date(2026, 5, 20), 14, "Executive handover meeting",
         "Outgoing and incoming executives: handover meeting on Wednesday 27 May, 4:00 pm, departmental office.",
         "executives", None, "normal", "General Secretary", 10),
    ],
    1: [
        (date(2026, 8, 25), 9, "Welcome back to the 2026/2027 academic year",
         "Akwaaba! Please confirm your membership for 2026/2027 on DeptHub so your dues and notices are up to date.",
         "all_members", None, "normal", "President", 30),
        (date(2026, 8, 28), 12, "Departmental dues 2026/2027 - GHS 150, deadline 30 October",
         "Departmental dues for 2026/2027 are GHS 150.00, payable by 30 October 2026. Pay with MoMo, Paystack or "
         "cash at the departmental office.", "all_members", None, "important", "Financial Secretary", 63),
        (date(2026, 9, 7), 10, "Welcome, Level 100 freshers!",
         "Welcome to Computer Science and Engineering at UMaT. Create your DeptHub account with your student number "
         "to receive department notices.", "selected_levels", {"levels": ["Level 100"]}, "normal", "President", 30),
        (date(2026, 9, 21), 10, "Freshers' orientation - Friday 25 September",
         "All Level 100 students: orientation at the UMaT Auditorium, 9:00 am. Collect your orientation pack at the "
         "entrance.", "selected_levels", {"levels": ["Level 100"]}, "important", "Organising Secretary", 5),
        (date(2026, 9, 30), 16, "Orientation pack payment closes 9 October",
         "Level 100: the orientation pack (GHS 60) closes on 9 October.", "selected_levels",
         {"levels": ["Level 100"]}, "important", "Financial Secretary", 10),
        (date(2026, 10, 5), 18, "CSE Week 2027 early-bird T-shirt pre-orders",
         "Early-bird pre-orders for the CSE Week 2027 T-shirt (GHS 100) are open.", "all_members", None, "normal",
         "Public Relations Officer", 60),
        (date(2026, 10, 12), 17, "CSE Hackathon 2026 - registration open",
         "Registration is open for the CSE Hackathon on 13-14 November. Teams of 3-4. 80 places.",
         "all_members", None, "normal", "President", 30),
        (date(2026, 10, 19), 8, "Dues deadline in 11 days",
         "Departmental dues close on Friday 30 October. Check your balance on DeptHub and pay early to avoid the "
         "last-minute rush.", "all_members", None, "urgent", "Financial Secretary", 12),
        (date(2026, 10, 21), 13, "Executive meeting: hackathon logistics",
         "Executives: meeting on Wednesday 28 October, 4:00 pm, departmental office.", "executives", None, "normal",
         "General Secretary", 8),
    ],
}
SCHEDULED = (date(2026, 10, 27), 7, "Final reminder: dues close on Friday",
             "Final reminder: departmental dues (GHS 150) close this Friday, 30 October.", "all_members", None,
             "urgent", "Financial Secretary")
DRAFT = ("Mid-semester quiz schedule", "Draft: quiz dates for Level 200-400 courses to be confirmed with lecturers.",
         "selected_levels", {"levels": ["Level 200", "Level 300", "Level 400"]}, "normal", "General Secretary")
CANCELLED = (date(2026, 3, 2), "Inter-department football match", "Postponed: the match against Geomatic Engineering "
             "has been called off due to pitch maintenance.", "all_members", None, "normal", "Organising Secretary")


def build(ctx):
    rng = ctx.stream("comms")
    _announcements(ctx, rng)
    _notifications(ctx, rng)


def _announcements(ctx, rng):
    dept = ctx.ref["dept"]
    sessions = ctx.ref["sessions"]
    for sidx, items in ANNOUNCEMENTS.items():
        execs = ctx.ref["execs"][sidx]
        closed = sessions[sidx]["cfg"]["status"] == "closed"
        for day, hour, title, body, audience, filt, priority, author, expires in items:
            published = at(day, hour, rng.randint(0, 59))
            expires_at = at(day + timedelta(days=expires), 23, 59)
            status = "archived" if closed or expires_at < ctx.as_of else "published"
            updated = at(sessions[-1]["cfg"]["starts_on"], 7) if closed else published
            ctx.add("announcements", published - timedelta(minutes=rng.randint(10, 240)), updated,
                    department_id=dept["id"], title=title, body=body, audience_type=audience, audience_filter=filt,
                    priority=priority, announcement_status=status, created_by_id=execs[author]["id"],
                    published_at=published, expires_at=expires_at)
    execs = ctx.ref["execs"][1]
    day, hour, title, body, audience, filt, priority, author = SCHEDULED
    ctx.add("announcements", ctx.as_of - timedelta(hours=5), department_id=dept["id"], title=title, body=body,
            audience_type=audience, audience_filter=filt, priority=priority, announcement_status="scheduled",
            created_by_id=execs[author]["id"], published_at=at(day, hour), expires_at=at(date(2026, 10, 30), 23, 59))
    title, body, audience, filt, priority, author = DRAFT
    ctx.add("announcements", ctx.as_of - timedelta(days=2), department_id=dept["id"], title=title, body=body,
            audience_type=audience, audience_filter=filt, priority=priority, announcement_status="draft",
            created_by_id=execs[author]["id"])
    day, title, body, audience, filt, priority, author = CANCELLED
    ctx.add("announcements", at(day, 10), at(day + timedelta(days=2), 9), department_id=dept["id"], title=title,
            body=body, audience_type=audience, audience_filter=filt, priority=priority,
            announcement_status="cancelled", created_by_id=ctx.ref["execs"][0][author]["id"])


def _notifications(ctx, rng):
    as_of = ctx.as_of
    for rec in ctx.ref["payments"]:
        p = rec["row"]
        user_id = rec["m"]["user"]["id"]
        if p["payment_status"] == "failed":
            t = p["updated_at"]
            ctx.add("notifications", t, t + timedelta(hours=2), user_id=user_id, channel="in_app",
                    notification_type="payment_failed", title="Payment could not be confirmed",
                    body=f"Your payment of GHS {p['amount']} could not be confirmed. {p['notes']}",
                    delivery_status="read" if rng.random() < 0.8 else "delivered", sent_at=t,
                    read_at=t + timedelta(hours=rng.randint(1, 30)) if rng.random() < 0.8 else None)
            continue
        receipt = rec.get("receipt")
        if not receipt:
            continue
        t = receipt["issued_at"]
        names = ", ".join(it["plan"]["cfg"]["name"] for it in rec["items"])
        read = rng.random() < 0.75
        read_at = min(t + timedelta(minutes=int(rng.expovariate(1 / 600))), as_of) if read else None
        ctx.add("notifications", t, read_at or t, user_id=user_id, channel="in_app",
                notification_type="payment_confirmed", title=f"Payment confirmed - receipt {receipt['receipt_number']}",
                body=f"We have received GHS {p['amount']} for {names}. Receipt {receipt['receipt_number']}.",
                delivery_status="read" if read else "delivered", sent_at=t, read_at=read_at)
        if rec["method"] in ("mobile_money", "cash") and rng.random() < 0.6:
            failed = rng.random() < 0.02
            ctx.add("notifications", t, t + timedelta(seconds=40), user_id=user_id, channel="sms",
                    notification_type="payment_confirmed", title="Payment confirmed",
                    body=f"UMaT CSE: GHS {p['amount']} received. Receipt {receipt['receipt_number']}. Thank you.",
                    delivery_status="failed" if failed else "delivered", sent_at=t + timedelta(seconds=5),
                    delivery_error_code="DLR_UNDELIVERED" if failed else None)

    # Dues reminders to members with nothing paid towards mandatory dues at reminder time.
    paid_by = {}
    for rec in ctx.ref["payments"]:
        if rec["row"]["payment_status"] in ("confirmed", "pending", "refunded", "partially_refunded"):
            for it in rec["items"]:
                aid = it["plan"]["row"]["id"]
                paid_by[aid] = min(paid_by.get(aid, rec["row"]["initiated_at"]), rec["row"]["initiated_at"])
    reminders = {0: [at(date(2025, 10, 10), 8, 5)], 1: [at(date(2026, 10, 19), 8, 5)]}
    for plan in ctx.ref["assessment_plans"]:
        if plan["cfg"]["key"] != "dues" or plan["row"]["assessment_state"] != "active":
            continue
        if plan["m"]["status"] not in ("active", "graduated"):
            continue
        for t in reminders[plan["sidx"]]:
            first_paid = paid_by.get(plan["row"]["id"])
            if plan["row"]["assessed_at"] > t or (first_paid and first_paid <= t):
                continue
            uid = plan["m"]["user"]["id"]
            body = (f"UMaT CSE: your {plan['cfg']['name']} (GHS {plan['payable']}) is due on "
                    f"{plan['cfg']['due_date']:%d %b %Y}. Pay via MoMo, Paystack or at the dept office.")
            failed = rng.random() < 0.03
            ctx.add("notifications", t - timedelta(minutes=5), t + timedelta(minutes=1), user_id=uid, channel="sms",
                    notification_type="dues_reminder", title="Dues reminder", body=body,
                    delivery_status="failed" if failed else "delivered", scheduled_at=t,
                    sent_at=t + timedelta(seconds=rng.randint(5, 90)),
                    delivery_error_code="INVALID_DESTINATION" if failed else None)
            read = rng.random() < 0.55
            ctx.add("notifications", t - timedelta(minutes=5), t, user_id=uid, channel="email",
                    notification_type="dues_reminder", title=f"Reminder: {plan['cfg']['name']} due soon", body=body,
                    delivery_status="read" if read else "delivered", scheduled_at=t, sent_at=t,
                    read_at=rand_time(rng, t.date() + timedelta(days=rng.randint(0, 2)), (9, 22)) if read else None)
        # The final reminder is queued for next week for anyone still owing.
        if plan["sidx"] == 1 and plan["row"]["id"] not in paid_by:
            ctx.add("notifications", as_of - timedelta(hours=4), user_id=plan["m"]["user"]["id"], channel="sms",
                    notification_type="dues_reminder", title="Final dues reminder",
                    body=f"UMaT CSE: final reminder - {plan['cfg']['name']} (GHS {plan['payable']}) closes Fri 30 Oct.",
                    delivery_status="queued", scheduled_at=at(date(2026, 10, 27), 7))
