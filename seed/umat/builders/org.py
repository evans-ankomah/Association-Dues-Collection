"""institutions, faculties, departments, academic_sessions, roles, permissions (role_permissions come after users)."""
from datetime import timedelta

from .. import config, reference
from ..core import at


def build(ctx):
    launch = config.PLATFORM_LAUNCH
    inst = ctx.add("institutions", launch, name=reference.INSTITUTION["name"],
                   country_code=reference.INSTITUTION["country_code"], default_currency=config.CURRENCY,
                   timezone=config.TIMEZONE, status="active")
    ctx.ref["institution"] = inst

    departments = {}
    for i, (fcode, fname, depts) in enumerate(reference.FACULTIES):
        t = launch + timedelta(minutes=5 + i)
        fac = ctx.add("faculties", t, institution_id=inst["id"], code=fcode, name=fname, status="active")
        for j, (dcode, dname, short) in enumerate(depts):
            departments[dcode] = ctx.add(
                "departments", t + timedelta(seconds=10 * (j + 1)), institution_id=inst["id"], faculty_id=fac["id"],
                code=dcode, name=dname, short_name=short, official_email=f"{dcode.lower()}@{config.STAFF_EMAIL_DOMAIN}",
                default_currency=config.CURRENCY, timezone=config.TIMEZONE, status="active")
    ctx.ref["departments"] = departments
    ctx.ref["dept"] = departments[config.FOCUS_DEPARTMENT_CODE]

    sessions = []
    for cfg in config.SESSIONS:
        created = min(at(cfg["starts_on"] - timedelta(days=14), 10), ctx.as_of)
        if created < launch:
            created = launch + timedelta(minutes=30)
        # The closed session was flipped to closed at the start of the next one.
        updated = at(config.SESSIONS[-1]["starts_on"], 7) if cfg["status"] == "closed" else created
        row = ctx.add("academic_sessions", created, updated, institution_id=inst["id"], name=cfg["name"],
                      starts_on=cfg["starts_on"], ends_on=cfg["ends_on"], is_current=cfg["is_current"],
                      status=cfg["status"])
        sessions.append({"row": row, "cfg": cfg})
    ctx.ref["sessions"] = sessions

    roles = {}
    for code, name, scope, is_system, desc in reference.ROLES:
        roles[code] = ctx.add("roles", launch, role_code=code, name=name, scope_type=scope, description=desc,
                              is_system_role=is_system)
    ctx.ref["roles"] = roles

    perms = {}
    for code, module, action, desc in reference.PERMISSIONS:
        perms[code] = ctx.add("permissions", launch, permission_code=code, module_key=module, action_key=action,
                              description=desc)
    ctx.ref["permissions"] = perms


def build_role_permissions(ctx):
    admin = ctx.ref["staff"]["platform_admin"]
    t = admin["created_at"] + timedelta(hours=1)
    for role_code, perm_codes in reference.ROLE_PERMISSIONS.items():
        for code in perm_codes:
            ctx.add("role_permissions", t, role_id=ctx.ref["roles"][role_code]["id"],
                    permission_id=ctx.ref["permissions"][code]["id"], created_by_id=admin["id"])
