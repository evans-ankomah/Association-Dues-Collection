# Architecture

DeptHub is a **modular monolith**: one Django project, one PostgreSQL database, and clear module boundaries. There are no microservices; background work runs on Celery with Redis.

```
Browser ──HTTP──> Django (gunicorn)
                    ├── middleware: request id, department context, sessions, CSRF
                    ├── views (HTML + HTMX)  ─┐
                    ├── /api/v1 (DRF)        ─┼─> services (business rules, permissions, locking, audit)
                    └── webhooks (Paystack)  ─┘            │
                                                           ▼
                                                     PostgreSQL ── v_dues_balances (view)
                    Celery worker + beat <── Redis ──> notifications, reminders, checkout clean-up
```

## Modules (`apps/`)

| App | Owns |
|---|---|
| `common` | Base model (UUID key, timestamps), money fields, navigation, seed loader, health check |
| `institutions` | Institutions, faculties, departments, academic sessions |
| `accounts` | Login identity (`User`), profiles, sign-in, password reset, login throttling |
| `memberships` | Department membership per session, member roster |
| `access` | Roles, permissions, scoped role assignments, `has_perm`, department/session context |
| `audit` | Append-only audit events, request ids |
| `finance` | Dues types, assessments, waivers, payments, allocations, receipts, Paystack, refunds, reconciliation, budgets, expenses, reminders |
| `communications` | Notices, notifications (in-app, email, SMS) |
| `events` | Events, registration, waitlists, attendance |
| `service_requests` | Service requests, comments, restricted visibility |
| `documents` | Private document store, versions, review |
| `workspace` | Committees, meetings, tasks |
| `resources` | Assets and resource bookings |
| `reporting` | Dashboards, finance report, exports |
| `api` | REST API v1 and OpenAPI schema |

Views and API endpoints are thin. Business rules live in `apps/*/services*.py`, and those services:

- re-check permissions, so they're safe to call from anywhere;
- run in a database transaction and lock the rows they change (`select_for_update`);
- write an audit event.

## Money rules

- All amounts are `numeric(12,2)` with an explicit currency (GHS). Floats are never used.
- **Balances are calculated, never stored.** `balance = assessed − waived − allocations on received payments + amounts reversed by processed adjustments`. The same rule exists as the ORM annotation `finance.services.balances.with_balances` and as the SQL view `v_dues_balances`. Tests check both against the seed validator.
- A payment counts as income only once it's `confirmed` (or later refunded). Online payments are confirmed only from a signed Paystack webhook or a server-side verify call, and only when status, reference, currency and amount all match.
- Completed records are never edited or deleted. Corrections go through refunds, reversals or voids, each requested, approved and processed by different people.
- Only `paid` expenses count as cash outflow.

## Operations rules

- **Events.** Members register themselves; attendance is recorded by an organiser, never
  self-asserted. A full event waitlists rather than refusing, and cancelling a seat promotes
  the longest-waiting member. Drafts are invisible to members, and a user with no role in a
  department sees none of its events.
- **Service requests.** A `restricted` request is visible only to its requester and assignee —
  `requests.manage` alone never opens one, so a welfare case never reaches the general queue.
  Sensitive types (welfare, result queries) are forced to restricted on submission, so a
  tampered form field can't publish one. `staff_only` comments are never shown to the requester.
- **Documents.** Files live outside `MEDIA_ROOT` in the `documents` storage backend and are
  never reachable by URL; the only read path is a view that checks `can_read` first, and every
  download is audited. Storage keys are opaque UUIDs scoped by department. Size and MIME type
  are validated before anything is written, SHA-256 is recorded, and a new version supersedes
  rather than overwrites. A document is reviewed by someone other than its uploader.
- **Bookings.** An asset can be held by one booking at a time. That is enforced by a Postgres
  `ExclusionConstraint` (`btree_gist`, `tstzrange` with an exclusive end) over approved and
  checked-out bookings, so two approvals racing each other still can't double-book; the service
  turns the resulting `IntegrityError` into a readable message. Requested bookings may overlap
  freely, back-to-back bookings are allowed, and nobody approves their own.

## Department and session context

`DepartmentContextMiddleware` puts `request.department` and `request.academic_session` on every request. The department is always chosen from the user's own role assignments; a value in the session isn't trusted on its own. Every query is filtered by `request.department`, so another department's record returns 404.

## Background jobs

| Job | Schedule | What it does |
|---|---|---|
| `finance.tasks.send_dues_reminders` | daily 09:00 | due-soon / overdue / final reminders, once per member and stage |
| `finance.tasks.resolve_abandoned_checkouts` | hourly | asks Paystack about old pending checkouts, cancels the rest |
| `communications.tasks.deliver_notification` | on demand | sends one email or SMS notification |
| `communications.tasks.fan_out_announcement` | on demand | notifies the audience of an important or urgent notice |

No job sweeps the notification queue. Only notifications the app creates are delivered, so imported rows are never sent.

## Workbook alignment

Table and column names follow `.product/DeptHub_Database_Design.xlsx`, so `load_umat_seed` loads the sample data 1:1. A few additions outside the workbook are marked in the models:

- `waiver_requests`
- `receipt_counters`
- `announcement_acknowledgements`
- notification `link` and `dedupe_key`
- profile notification preferences
- `payments.intended_allocations`
