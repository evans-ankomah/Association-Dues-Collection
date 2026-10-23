# UMaT sample data for DeptHub

This generator builds a realistic but **anonymised** dataset for the DeptHub target schema (`.product/DeptHub_Database_Design.xlsx`). It models the Computer Science & Engineering (CSE) department at the University of Mines and Technology (UMaT), Tarkwa. All other UMaT faculties and departments are included as records but have no members.

It uses only the Python 3.10+ standard library (`openpyxl` is needed only to regenerate the schema). The same seed always produces byte-identical output.

```bash
python seed/generate_umat.py            # writes seed/output/{csv,json}/<table>.csv|json + manifest.json
python seed/validate_umat.py            # integrity checks + realism summary (exit 1 on failure)
python seed/generate_umat.py --seed 7   # a different but equally valid dataset
python seed/regenerate_schema.py        # rebuild umat/schema.py after the workbook changes
```

## What's in it

- **Snapshot date:** 22 Oct 2026. There are two sessions: **2025/2026 (closed)** and **2026/2027 (current, ~8 weeks in)**.
- **Members:** about 410–420 CSE members per session (Levels 100–400) and 525 students overall.
  - The 2025/26 Level 400 class graduates.
  - The other cohorts move up a level, with a few transfers and withdrawals.
  - A new Level 100 intake joins in 2026/27.
- **Staff and executives:**
  - Seven staff users: HoD, faculty adviser, department administrator, platform admin, auditor and two partner-department reps.
  - Elected executives each session: President, General Secretary, Financial Secretary, Treasurer, VP, Organising Secretary, Women's Commissioner and PRO.
- **Dues:** departmental dues of GHS 120 → GHS 150, plus optional T-shirts, the Level 300 industrial visit, the final-year dinner and the freshers' orientation pack.
  - The closed session is about 84% collected.
  - The current session is about 50% collected, with the 30 Oct deadline still ahead.
  - Waivers have reasons attributed to the HoD.
- **Payments:**
  - Mix: MoMo about 60% (MTN MoMo, Telecel Cash and AT Money, matched to each student's phone network), Paystack about 18% (with `webhook_events`), cash about 16% and bank transfer about 6%.
  - Edge cases: instalments, one payment covering several dues, failed and abandoned attempts, pending verifications, three duplicate MoMo payments refunded in full, and one overpayment partly refunded.
  - Receipts are numbered `CSE-<year>-<seq>`.
- **Finance:** budgets per activity, expense requests with a two-step approval (President, then HoD/adviser), and paid expenses from fictitious Tarkwa vendors.
- **Operations:** announcements, notifications (receipts and dues reminders, including queued ones), events with registrations and QR attendance, committees, meetings, tasks, service requests with comments, and an audit trail.

There are 36 of the 44 tables. Not generated yet: `documents`, `assets`, `resource_bookings`, `surveys`, `survey_questions`, `survey_responses`, `collaboration_projects` and `collaboration_departments`. Optional FKs to these tables are left null.

## File format

- **CSV:** one file per table, with columns in workbook order.
  - Timestamps are ISO-8601 UTC (`2025-10-08T12:44:24Z`). Ghana is UTC+0, so UTC is also local time.
  - Money is fixed 2-decimal strings in `GHS`.
  - Booleans are `true`/`false`, `jsonb` columns are JSON text, and an empty cell means NULL.
- **JSON:** the same rows as arrays of objects, with native booleans and nulls and money kept as strings.
- **Load order:** follow `manifest.json` → `row_counts`, which lists tables in workbook order. Faculties come before departments, and users before everything that references them.
- **Balances are not stored.** Calculate them as in `v_dues_balances`: assessed − waived − confirmed allocations + processed reversals. `validate_umat.py` does exactly this.

## Assumptions to review

| Item | What the data uses | Why |
|---|---|---|
| Faculty/department list | UMaT structure as published on Wikipedia (checked Oct 2026) | The official site blocks automated reads. Edit `umat/reference.py` if needed. |
| Student number | `CE-<entry year>-<4 digits>` | UMaT's real format isn't public. Change it with `STUDENT_NUMBER_PATTERN` in `umat/config.py`. |
| Dues amounts and rates | GHS 120/150 dues and the other amounts in `umat/config.py` | There is no published UMaT figure. These are typical for Ghanaian departmental associations. |
| Emails | `@st.umat.test` / `@umat.test` | Non-routable domains, so no real inbox can be reached. |
| Staff, vendors, venues | Fictitious names; generic campus venues | Avoids implying real people or businesses. |

## ⚠ Safety

The phone numbers use **real Ghanaian network prefixes** (`233` + 24/54/55/59/53/25/20/50/26/56/27/57), so some may belong to real people.

- **Never** run the Celery SMS or email tasks (`payments/tasks.py`, Deywuro, SMTP) against a database loaded with this data.
- Disable the beat schedule, or point the SMS sender at a sandbox.

## Layout

```
seed/
  generate_umat.py      entry point
  validate_umat.py      integrity checks + summary
  regenerate_schema.py  workbook -> umat/schema.py
  umat/
    config.py           every tunable number: dates, volumes, dues, rates, method mix
    reference.py        UMaT faculties/departments, staff, roles/permissions, venues, banks
    names.py            Ghanaian name pools (Akan, Fante/Western, Ewe, Ga-Adangbe, Northern)
    schema.py           generated table/column/enum/FK definitions
    core.py, ids.py, writer.py
    builders/           org, people, dues, payments, finance, comms, ops, audit
```

Each builder draws from its own named random stream. Changing one area (for example, adding events) doesn't reshuffle the others.
