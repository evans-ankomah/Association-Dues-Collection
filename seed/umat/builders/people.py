"""users, user_profiles, department_memberships, role_assignments.

Cohorts flow across the two sessions: 2025/26 Level 400 graduate, the other cohorts move up one level
(minus a few transfers/withdrawals) and a new Level 100 intake joins in 2026/27.
"""
import re
from datetime import timedelta

from .. import config, ids, reference
from ..core import at, rand_time, weighted_day
from ..names import NameGen

LEVELS = (100, 200, 300, 400)


class People:
    def __init__(self, ctx):
        self.ctx = ctx
        self.rng = ctx.stream("people")
        self.names = NameGen(self.rng)
        self.emails = set()
        self.phones = set()
        self.inst = ctx.ref["institution"]

    def _email(self, given, family, domain, staff=False):
        clean = lambda s: re.sub(r"[^a-z]", "", s.lower())
        while True:
            if staff:
                local = f"{clean(given)[0]}{clean(family)}"
                if local not in self.emails:
                    break
                local += str(self.rng.randint(1, 9))
            else:
                local = f"{clean(given)}.{clean(family)}{self.rng.randint(1, 99):02d}"
            if local not in self.emails:
                break
        self.emails.add(local)
        return f"{local}@{domain}"

    def _phone(self):
        while True:
            network, number = ids.phone_number(self.rng)
            if number not in self.phones:
                self.phones.add(number)
                return network, number

    def make_user(self, created_at, given, middle, family, *, staff_title=None, student_number=None,
                  auth_provider="local", is_platform_admin=False):
        domain = config.STAFF_EMAIL_DOMAIN if staff_title else config.STUDENT_EMAIL_DOMAIN
        email = self._email(given, family, domain, staff=bool(staff_title))
        user = self.ctx.add("users", created_at, email=email, is_active=True, is_platform_admin=is_platform_admin,
                            auth_provider=auth_provider, last_login_at=None)
        network, phone = self._phone()
        full = " ".join(p for p in (given, middle, family) if p)
        display = f"{staff_title} {given} {family}" if staff_title else full
        profile = self.ctx.add("user_profiles", created_at, user_id=user["id"], institution_id=self.inst["id"],
                               student_number=student_number, given_name=given, family_name=family,
                               display_name=display, phone_number=phone,
                               preferred_language="en" if self.rng.random() < 0.9 else None)
        return {"user": user, "profile": profile, "network": network}


def build(ctx):
    p = People(ctx)
    rng = p.rng
    dept = ctx.ref["dept"]
    sessions = ctx.ref["sessions"]
    roles = ctx.ref["roles"]
    s1, s2 = sessions[0], sessions[1]

    # --- staff ----------------------------------------------------------------
    staff, staff_people = {}, {}
    for i, (key, (title, given, family, role_codes, dept_code)) in enumerate(reference.STAFF.items()):
        created = config.PLATFORM_LAUNCH + timedelta(hours=1 + i)
        person = p.make_user(created, given, None, family, staff_title=title, auth_provider="institutional_sso",
                             is_platform_admin=(key == "platform_admin"))
        person.update(key=key, role_codes=role_codes, dept_code=dept_code)
        staff[key] = person["user"]
        staff_people[key] = person
    ctx.ref["staff"] = staff
    admin = staff["platform_admin"]
    for person in staff_people.values():
        for code in person["role_codes"]:
            role = roles[code]
            scoped_dept = ctx.ref["departments"][person["dept_code"]] if role["scope_type"] == "department" else None
            ctx.add("role_assignments", person["user"]["created_at"] + timedelta(minutes=20),
                    user_id=person["user"]["id"], role_id=role["id"],
                    department_id=scoped_dept["id"] if scoped_dept else None,
                    starts_at=person["user"]["created_at"] + timedelta(minutes=20), assignment_status="active",
                    assigned_by_id=admin["id"])

    # --- students ---------------------------------------------------------------
    s1_start = s1["cfg"]["starts_on"]
    s1_year = s1_start.year

    def new_cohort(n, entry_year):
        serials = sorted(rng.sample(range(1, n + 40), n))
        cohort = []
        for serial in serials:
            female = rng.random() < config.FEMALE_SHARE
            given, middle, family = p.names.person(female)
            cohort.append({"female": female, "given": given, "middle": middle, "family": family,
                           "student_number": ids.student_number(entry_year, serial), "entry_year": entry_year})
        return cohort

    cohorts1 = {lvl: new_cohort(n, s1_year - (lvl // 100 - 1)) for lvl, n in s1["cfg"]["level_sizes"].items()}
    intake2 = new_cohort(s2["cfg"]["new_intake"], s2["cfg"]["starts_on"].year)

    # Executives are chosen first so they register on day one.
    def pick_execs(by_level, exclude):
        chosen = {}
        for office, role_code, level in reference.EXEC_OFFICES:
            taken = exclude | {id(x) for x in chosen.values()}
            pool = [s for s in by_level[level] if id(s) not in taken]
            if office == "Women's Commissioner":
                pool = [s for s in pool if s["female"]]
            chosen[office] = rng.choice(pool)
        return chosen

    execs1 = pick_execs(cohorts1, set())
    exec1_ids = {id(s) for s in execs1.values()}

    leavers = {}
    for lvl, n in config.ATTRITION.items():
        candidates = [s for s in cohorts1[lvl] if id(s) not in exec1_ids]
        for s in rng.sample(candidates, n):
            leavers[id(s)] = rng.choice(["transferred", "inactive"])

    cohorts2 = {100: intake2}
    for lvl in (100, 200, 300):
        cohorts2[lvl + 100] = [s for s in cohorts1[lvl] if id(s) not in leavers]
    execs2 = pick_execs(cohorts2, set())
    exec2_ids = {id(s) for s in execs2.values()}

    # --- memberships -------------------------------------------------------------
    memberships = {0: [], 1: []}

    def join_time(session_idx, level, is_exec):
        cfg = sessions[session_idx]["cfg"]
        start = cfg["starts_on"]
        if is_exec:
            return at(start, 8, rng.randint(0, 59))
        if level == 100:
            lo, hi = start + timedelta(days=14), start + timedelta(days=53)
        else:
            lo, hi = start, start + timedelta(days=30)
        day = weighted_day(rng, lo, hi, lambda d: 1.0 / (1 + (d - lo).days / 6))
        return min(rand_time(rng, day, (7, 22)), ctx.as_of - timedelta(hours=2))

    def add_membership(session_idx, student, level, status, exec_ids):
        sess = sessions[session_idx]
        is_exec = id(student) in exec_ids
        joined = join_time(session_idx, level, is_exec)
        if "person" not in student:
            student["person"] = p.make_user(joined, student["given"], student["middle"], student["family"],
                                            student_number=student["student_number"])
        user = student["person"]["user"]
        gen_sec = None if is_exec else (execs1 if session_idx == 0 else execs2)["General Secretary"]
        verifier = staff["hod"] if gen_sec is None else gen_sec["person"]["user"]
        verified_at = joined + timedelta(days=rng.randint(0, 4), hours=rng.randint(1, 8))
        if verified_at > ctx.as_of or (level == 100 and session_idx == 1 and
                                       (ctx.as_of - joined).days < 6 and rng.random() < 0.5):
            verified_at, verifier = None, None
        left_on = None
        updated = verified_at or joined
        if status == "graduated":
            left_on = sess["cfg"]["sem2"][1]
            updated = at(sessions[1]["cfg"]["starts_on"], 7)
        elif status in ("transferred", "inactive") and session_idx == 0:
            left_on = weighted_day(rng, sess["cfg"]["sem2"][0], sess["cfg"]["sem2"][0] + timedelta(days=90),
                                   lambda d: 1.0)
            updated = at(left_on, 10)
        elif status in ("inactive", "suspended"):
            left_on = None
            updated = ctx.as_of - timedelta(days=rng.randint(5, 30))
        row = ctx.add("department_memberships", joined, updated, department_id=dept["id"], user_id=user["id"],
                      academic_session_id=sess["row"]["id"], programme_name=config.PROGRAMME_NAME,
                      level_code=f"Level {level}", membership_status=status, joined_on=joined.date(),
                      left_on=left_on, verified_by_id=verifier["id"] if verifier else None, verified_at=verified_at)
        m = {"row": row, "student": student, "session_idx": session_idx, "level": level, "status": status,
             "joined_at": joined, "left_on": left_on, "user": user}
        memberships[session_idx].append(m)
        return m

    # Execs register first so that verifiers exist before everyone else.
    for session_idx, cohorts, execs, exec_ids in ((0, cohorts1, execs1, exec1_ids), (1, cohorts2, execs2, exec2_ids)):
        for s in execs.values():
            lvl = next(lv for lv, c in cohorts.items() if any(x is s for x in c))
            add_membership(session_idx, s, lvl, "active", exec_ids)
        if session_idx == 0:
            for lvl in LEVELS:
                for s in cohorts[lvl]:
                    if id(s) in exec_ids:
                        continue
                    status = "graduated" if lvl == 400 else leavers.get(id(s), "active")
                    add_membership(0, s, lvl, status, exec_ids)
            # Execs who were Level 400 also graduated.
            for m in memberships[0]:
                if m["level"] == 400 and m["status"] == "active":
                    m["status"] = m["row"]["membership_status"] = "graduated"
                    m["row"]["left_on"] = m["left_on"] = sessions[0]["cfg"]["sem2"][1]
                    m["row"]["updated_at"] = at(sessions[1]["cfg"]["starts_on"], 7)
        else:
            others = [(lvl, s) for lvl in LEVELS for s in cohorts[lvl] if id(s) not in exec_ids]
            quiet = rng.sample([x for x in others if x[0] != 100],
                               config.CURRENT_INACTIVE + config.CURRENT_SUSPENDED)
            quiet_status = {id(s): ("suspended" if i < config.CURRENT_SUSPENDED else "inactive")
                            for i, (_, s) in enumerate(quiet)}
            for lvl, s in others:
                add_membership(1, s, lvl, quiet_status.get(id(s), "active"), exec_ids)

    # --- user activity -------------------------------------------------------------
    for sidx in (0, 1):
        for m in memberships[sidx]:
            user = m["user"]
            if m["status"] == "graduated":
                last = rand_time(rng, weighted_day(rng, m["left_on"] - timedelta(days=20), m["left_on"] +
                                                   timedelta(days=60), lambda d: 1.0), (8, 22))
            elif m["status"] in ("transferred", "inactive") and sidx == 0:
                last = at(m["left_on"], 9) - timedelta(days=rng.randint(1, 20))
                if m["status"] == "transferred":
                    user["is_active"] = False
            elif sidx == 1:
                if m["status"] == "active":
                    last = ctx.as_of - timedelta(hours=rng.expovariate(1 / 90))
                else:
                    last = ctx.as_of - timedelta(days=rng.randint(30, 60))
            else:
                continue
            last = max(min(last, ctx.as_of), user["created_at"] + timedelta(minutes=5))
            user["last_login_at"] = last
            user["updated_at"] = max(user["updated_at"], last)
    for person in staff_people.values():
        u = person["user"]
        u["last_login_at"] = u["updated_at"] = ctx.as_of - timedelta(hours=rng.randint(1, 200))

    # --- role assignments for students ---------------------------------------------
    session_end = lambda sidx: at(sessions[1]["cfg"]["starts_on"], 7) if sidx == 0 else None
    for sidx, execs in ((0, execs1), (1, execs2)):
        sess = sessions[sidx]
        gen_sec_user = execs["General Secretary"]["person"]["user"]
        for m in memberships[sidx]:
            ends_at, status = session_end(sidx), ("ended" if sidx == 0 else "active")
            if m["left_on"] and m["status"] != "graduated":
                ends_at = at(m["left_on"], 10)
            if sidx == 1 and m["status"] == "suspended":
                status, ends_at = "revoked", m["row"]["updated_at"]
            elif sidx == 1 and m["status"] == "inactive":
                status, ends_at = "ended", m["row"]["updated_at"]
            assigner = staff["hod"] if m["user"] is gen_sec_user else gen_sec_user
            ctx.add("role_assignments", m["joined_at"], ends_at or m["joined_at"],
                    user_id=m["user"]["id"], role_id=roles["student_member"]["id"], department_id=dept["id"],
                    academic_session_id=sess["row"]["id"], starts_at=m["joined_at"], ends_at=ends_at,
                    assignment_status=status, assigned_by_id=assigner["id"])
        for office, role_code, _ in reference.EXEC_OFFICES:
            s = execs[office]
            starts = at(sess["cfg"]["starts_on"], 8)
            ends = session_end(sidx)
            ctx.add("role_assignments", starts, ends or starts, user_id=s["person"]["user"]["id"],
                    role_id=roles[role_code]["id"], department_id=dept["id"], academic_session_id=sess["row"]["id"],
                    starts_at=starts, ends_at=ends, assignment_status="ended" if ends else "active",
                    assigned_by_id=staff["hod"]["id"])

    def exec_users(execs):
        return {office: s["person"]["user"] for office, s in execs.items()}

    def exec_memberships(sidx, execs):
        by_user = {m["user"]["id"]: m for m in memberships[sidx]}
        return {office: by_user[s["person"]["user"]["id"]] for office, s in execs.items()}

    ctx.ref["memberships"] = memberships
    ctx.ref["execs"] = {0: exec_users(execs1), 1: exec_users(execs2)}
    ctx.ref["exec_memberships"] = {0: exec_memberships(0, execs1), 1: exec_memberships(1, execs2)}
    ctx.ref["networks"] = {m["user"]["id"]: m["student"]["person"]["network"]
                           for sidx in (0, 1) for m in memberships[sidx]}
    ctx.ref["female"] = {m["user"]["id"]: m["student"]["female"] for sidx in (0, 1) for m in memberships[sidx]}

