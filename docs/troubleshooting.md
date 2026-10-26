# Troubleshooting

## Local development

| Symptom | Cause and fix |
|---|---|
| `password authentication failed for user "depthub"` | Another PostgreSQL is on port 5432. DeptHub's container uses **5433**: check `DATABASE_URL` points at `localhost:5433` and `docker compose ps` shows `db` healthy. |
| `failed to connect to the docker API` | Start Docker Desktop, then `docker compose up -d`. |
| Pages have no styling | Run `npm install && npm run build` (creates `static/css/app.css` and `static/vendor/`). |
| Commands are very slow on Windows | Antivirus scanning the project folder. Exclude the project folder (or at least `.venv` and `node_modules`) from real-time scanning. |
| `load_umat_seed` says the database already has users | Re-run with `--flush` (deletes all DeptHub data). |

## Payments

| Symptom | Cause and fix |
|---|---|
| "Online payment isn't available yet" | `PAYSTACK_SECRET_KEY` isn't set. |
| Paid on Paystack but still *pending* | The webhook didn't arrive or failed. Check the webhook URL in the Paystack dashboard, then use **Reconciliation → Check all with Paystack**. That asks Paystack directly and is safe to repeat. |
| Paystack payment flagged "did not match" | The amount or currency confirmed by Paystack differs from what DeptHub expected. The payment stays pending on purpose. Check the transaction in Paystack, then refund or confirm by contacting the payer. |
| Webhook returns 401 | The signature didn't verify: the secret key in DeptHub differs from the one Paystack signs with (test vs live). |
| Treasurer can't verify a payment | They recorded it, or it's their own payment. Another finance officer with `finance.payment.verify` must verify it. |
| Receipt number gap | Numbers are reserved inside the confirming transaction. A failed confirmation rolls the number back, so gaps shouldn't occur. If you see one, check the audit log for `payment.confirmed` around that time. |

## Access

| Symptom | Cause and fix |
|---|---|
| "Access denied" for an executive | Their role assignment has ended, has a future start, or is for another department. Check *Role assignments* in the Django admin. |
| Someone sees the wrong department | They hold roles in several departments. Use the department switcher at the top of the page. |
| "Too many failed attempts" | Five failed sign-ins in 15 minutes lock that email address for 15 minutes. Wait, or send a password reset from the Django admin. |
| Expense request can't be submitted: "No one currently holds the President role" | Assign the President (step 1) and HoD/adviser (step 2) roles for the department. |

## Reading logs

Every log line carries a request id (`[3f2a…]`). The same id is returned in the `X-Request-ID` response header and stored on audit events, so you can go from a user's error report to the exact log lines and audit trail.
