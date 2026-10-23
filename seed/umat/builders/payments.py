"""financial_accounts, payments, payment_allocations, receipts, payment_adjustments,
payment_allocation_adjustments, webhook_events.

Payment flows modelled:
- mobile_money: student sends to the association's MoMo merchant and submits the transaction ID;
  the Treasurer confirms it against the merchant statement (hours to days later).
- provider: Paystack checkout (card or MoMo channel); confirmed by verified webhook within seconds.
- cash: collected by the Financial Secretary, confirmed by the Treasurer on reconciliation.
- bank_transfer: deposit/transfer to the association bank account, confirmed when it appears on the statement.
"""
import hashlib
import json
import math
from collections import defaultdict
from datetime import timedelta

from .. import config, ids, reference
from ..core import MOMO_HOURS, OFFICE_HOURS, at, holiday_factor, money, next_weekday, rand_time, weighted_day

METHODS = list(config.METHOD_WEIGHTS)
FAILED_MOMO_NOTES = ["Submitted transaction ID not found on merchant statement.",
                     "Amount on MoMo statement does not match the submitted claim; student asked to resubmit."]
FAILED_PROVIDER_NOTES = ["Paystack: customer did not authorise the mobile money prompt (timed out).",
                         "Paystack: declined - insufficient funds.",
                         "Paystack: card declined by issuing bank."]


def build(ctx):
    b = PaymentBuilder(ctx)
    b.accounts()
    b.payments()
    b.duplicates_and_overpayments()
    b.receipts()
    b.stray_webhooks()
    ctx.ref["payments"] = b.records


class PaymentBuilder:
    def __init__(self, ctx):
        self.ctx = ctx
        self.rng = ctx.stream("payments")
        self.dept = ctx.ref["dept"]
        self.records = []
        self.used_refs = set()

    # --- accounts --------------------------------------------------------------------
    def accounts(self):
        ctx, rng = self.ctx, self.rng
        t = at(ctx.ref["sessions"][0]["cfg"]["starts_on"], 9, 30)
        specs = [
            ("CSE Students' Association Cash Box", "cash", None, None),
            ("CSE Association MoMo Merchant Wallet", "mobile_money", "MTN MoMo", f"23324****{rng.randint(100, 999)}"),
            ("Paystack Settlement - CSE Association", "online_clearing", "Paystack",
             f"ACCT_****{''.join(rng.choice('abcdefghjkmnpqrstuvwxyz0123456789') for _ in range(4))}"),
            (f"{reference.ASSOCIATION_BANK} Tarkwa - CSE Students' Association", "bank", reference.ASSOCIATION_BANK,
             f"****{rng.randint(1000, 9999)}"),
        ]
        ctx.ref["accounts"] = {}
        for name, kind, provider, masked in specs:
            ctx.ref["accounts"][kind] = ctx.add(
                "financial_accounts", t, department_id=self.dept["id"], name=name, account_type=kind,
                currency=config.CURRENCY, provider_name=provider, account_reference_masked=masked, is_active=True)

    # --- regular payments ------------------------------------------------------------------
    def payments(self):
        ctx, rng = self.ctx, self.rng
        pref = {}
        intents = defaultdict(list)
        for plan in ctx.ref["assessment_plans"]:
            if plan["outcome"] in ("outstanding", "cancelled", "waived_full"):
                continue
            payable = plan["payable"]
            if plan["outcome"] == "partial":
                parts = [max(money(10), _round5(float(payable) * rng.choice([0.25, 0.4, 0.5, 0.5, 0.6, 0.75])))]
            elif payable >= 100 and rng.random() < config.INSTALMENT_SHARE:
                first = _round5(float(payable) * rng.uniform(0.4, 0.7))
                parts = [first, payable - first]
            else:
                parts = [payable]
            day = self._first_pay_day(plan)
            if day is None:
                continue
            for i, amount in enumerate(parts):
                if i:
                    day = day + timedelta(days=rng.randint(10, 45))
                    if day > self._window_end(plan):
                        break  # second instalment not paid yet / at all
                intents[plan["m"]["row"]["id"]].append({"plan": plan, "amount": money(amount), "day": day})

        for m_id, items in intents.items():
            items.sort(key=lambda x: x["day"])
            groups = []
            for it in items:
                if groups and (it["day"] - groups[-1]["day"]).days <= 3 \
                        and it["plan"] not in [g["plan"] for g in groups[-1]["items"]] \
                        and rng.random() < config.BUNDLE_SHARE:
                    groups[-1]["items"].append(it)
                else:
                    groups.append({"day": it["day"], "items": [it]})
            for g in groups:
                m = g["items"][0]["plan"]["m"]
                uid = m["user"]["id"]
                if uid not in pref:
                    pref[uid] = rng.choices(METHODS, [config.METHOD_WEIGHTS[k] for k in METHODS])[0]
                self._pay(m, g["day"], g["items"], pref[uid])

    def _window_end(self, plan):
        end = plan["cfg"]["pay_window_end"] or self.ctx.as_of.date()
        return min(end, self.ctx.as_of.date())

    def _first_pay_day(self, plan):
        rng, cfg = self.rng, plan["cfg"]
        start = plan["row"]["assessed_at"].date()
        end = self._window_end(plan)
        if end < start:
            return None
        if not cfg["mandatory"] or cfg["key"] == "orientation":
            # Optional items are usually paid when ordered.
            return min(start + timedelta(days=int(rng.expovariate(1 / 2.5))), end)
        due = cfg["due_date"]

        def weight(d):
            since = (d - start).days
            to_due = (due - d).days
            if to_due >= 0:
                w = 1 + 3 * math.exp(-since / 7) + 5 * math.exp(-to_due / 4)
            else:
                w = 1.2 * math.exp(to_due / 14) + 0.04  # stragglers, then a thin tail through the session
            if plan["z"] < -0.5:
                w *= 0.4 if to_due > 7 else 2.0  # late payers cluster near/after the deadline
            return w * holiday_factor(d)
        return weighted_day(rng, start, end, weight)

    def _pay(self, m, day, items, preferred):
        ctx, rng = self.ctx, self.rng
        total = sum((it["amount"] for it in items), money(0))
        method = preferred if rng.random() < 0.8 else rng.choices(METHODS, [config.METHOD_WEIGHTS[k] for k in METHODS])[0]
        if total >= 300 and rng.random() < 0.2:
            method = "bank_transfer"
        latest_assessed = max(it["plan"]["row"]["assessed_at"] for it in items)
        if method in ("cash", "bank_transfer"):
            day = next_weekday(day)
            t = rand_time(rng, day, OFFICE_HOURS)
        else:
            t = rand_time(rng, day, MOMO_HOURS)
        t = max(t, latest_assessed + timedelta(minutes=rng.randint(5, 90)))
        if t > ctx.as_of - timedelta(minutes=5):
            return

        if method in ("mobile_money", "provider") and rng.random() < config.FAILED_ATTEMPT_SHARE:
            ft = t - timedelta(minutes=rng.randint(3, 50))
            if ft > latest_assessed:
                self._create(m, ft, method, total, items=None, status="failed")
        if method == "provider" and rng.random() < config.ABANDONED_CHECKOUT_SHARE:
            ct = t - timedelta(hours=rng.randint(1, 20))
            if ct > latest_assessed:
                self._create(m, ct, method, total, items=None, status="cancelled")
        self._create(m, t, method, total, items)

    def _confirm_lag(self, method):
        rng = self.rng
        if method == "provider":
            return timedelta(seconds=rng.randint(3, 40))
        if method == "mobile_money":
            return timedelta(minutes=rng.randint(20, 90)) + timedelta(hours=rng.expovariate(1 / 14))
        if method == "cash":
            return timedelta(hours=rng.randint(2, 50))
        return timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 6))

    def _create(self, m, t, method, total, items, status=None):
        ctx, rng = self.ctx, self.rng
        sidx = m["session_idx"]
        execs = ctx.ref["execs"][sidx]
        treasurer, fin_sec = execs["Treasurer"], execs["Financial Secretary"]
        payer = m["user"]
        network = ctx.ref["networks"][payer["id"]]
        provider_name = provider_ref = idem = external = notes = None
        recorded_by = verified_by = None
        channel = None

        if method == "mobile_money":
            provider_name, external = network, self._unique(lambda: ids.momo_transaction_id(rng))
            recorded_by = payer
            notes = f"{network} transfer to association merchant wallet; transaction ID submitted by student."
        elif method == "provider":
            provider_name, provider_ref = "Paystack", self._unique(lambda: ids.paystack_reference(rng))
            idem = f"{rng.getrandbits(128):032x}"
            channel = "mobile_money" if rng.random() < 0.7 else "card"
        elif method == "cash":
            recorded_by = fin_sec
            notes = rng.choice(["Cash received at CSE departmental office.",
                                "Cash collected by Financial Secretary during lecture break.",
                                "Cash paid at executive desk during general meeting."])
        else:
            bank = rng.choice(reference.BANKS)
            provider_name = reference.ASSOCIATION_BANK
            external = self._unique(lambda: ids.bank_reference(rng, t.date()))
            recorded_by = payer
            notes = f"Transfer from {bank} account to association account; reference submitted by student."

        confirmed_at = None
        if status is None:
            confirmed_at = t + self._confirm_lag(method)
            if method in ("mobile_money", "cash", "bank_transfer") and confirmed_at.hour < 7:
                confirmed_at = confirmed_at.replace(hour=rng.randint(7, 10))
            status = "confirmed" if confirmed_at <= ctx.as_of else "pending"
            if status == "pending":
                confirmed_at = None
            elif method != "provider":
                verified_by = treasurer
        elif status == "failed":
            notes = rng.choice(FAILED_PROVIDER_NOTES if method == "provider" else FAILED_MOMO_NOTES)
            if method != "provider":
                verified_by = treasurer
        elif status == "cancelled":
            notes = "Paystack checkout abandoned before payment."

        settled = confirmed_at or (t + timedelta(hours=rng.randint(1, 30)) if status == "failed" else t)
        row = ctx.add("payments", t, min(settled, ctx.as_of), department_id=self.dept["id"],
                      payer_membership_id=m["row"]["id"], amount=total, currency=config.CURRENCY,
                      payment_method=method, payment_status=status, provider_name=provider_name,
                      provider_reference=provider_ref, idempotency_key=idem, external_reference=external,
                      recorded_by_id=recorded_by["id"] if recorded_by else None,
                      verified_by_id=verified_by["id"] if verified_by else None, initiated_at=t,
                      confirmed_at=confirmed_at, notes=notes)
        allocations = []
        if items and status in ("confirmed", "pending"):
            for it in items:
                allocations.append(ctx.add(
                    "payment_allocations", confirmed_at or t, payment_id=row["id"],
                    dues_assessment_id=it["plan"]["row"]["id"], amount_allocated=it["amount"],
                    allocated_by_id=verified_by["id"] if verified_by else None, allocated_at=confirmed_at or t))
        rec = {"row": row, "m": m, "items": items or [], "allocations": allocations, "method": method,
               "network": network, "channel": channel}
        self.records.append(rec)
        if method == "provider" and status == "confirmed":
            self._webhook(rec)
        return rec

    def _unique(self, make):
        while True:
            ref = make()
            if ref not in self.used_refs:
                self.used_refs.add(ref)
                return ref

    def _webhook(self, rec):
        ctx, rng = self.ctx, self.rng
        p = rec["row"]
        event_id = ids.paystack_transaction_id(rng)
        payload = {"event": "charge.success", "data": {"id": int(event_id), "reference": p["provider_reference"],
                                                       "amount": int(p["amount"] * 100), "currency": "GHS",
                                                       "channel": rec["channel"], "status": "success"}}
        received = p["confirmed_at"] - timedelta(seconds=1)
        ctx.add("webhook_events", received, p["confirmed_at"], provider_name="Paystack", provider_event_id=event_id,
                event_type="charge.success", received_at=received, signature_valid=True,
                processing_status="processed", processed_at=p["confirmed_at"],
                payload_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                safe_metadata={"reference": p["provider_reference"], "amount_pesewas": payload["data"]["amount"],
                               "currency": "GHS", "channel": rec["channel"]})

    def stray_webhooks(self):
        """Webhooks that failed signature checks (spoofed or misconfigured) and were ignored."""
        ctx, rng = self.ctx, self.rng
        for day in (ctx.ref["sessions"][0]["cfg"]["starts_on"] + timedelta(days=40),
                    ctx.as_of.date() - timedelta(days=12)):
            t = rand_time(rng, day, (0, 23))
            ref = ids.paystack_reference(rng)
            payload = {"event": "charge.success", "data": {"reference": ref, "amount": 15000}}
            ctx.add("webhook_events", t, t, provider_name="Paystack", provider_event_id=ids.paystack_transaction_id(rng),
                    event_type="charge.success", received_at=t, signature_valid=False, processing_status="ignored",
                    processed_at=t, payload_sha256=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
                    safe_metadata={"reason": "invalid_signature", "reference": ref})

    # --- refunds -------------------------------------------------------------------------
    def duplicates_and_overpayments(self):
        ctx, rng = self.ctx, self.rng
        hod = ctx.ref["staff"]["hod"]
        candidates = [r for r in self.records
                      if r["method"] == "mobile_money" and r["row"]["payment_status"] == "confirmed"
                      and len(r["items"]) == 1 and r["items"][0]["plan"]["cfg"]["key"] == "dues"
                      and r["row"]["confirmed_at"] + timedelta(days=12) < ctx.as_of]
        picked = rng.sample(candidates, config.DUPLICATE_REFUNDS + config.OVERPAYMENT_REFUNDS)

        for orig in picked[:config.DUPLICATE_REFUNDS]:
            p1 = orig["row"]
            t = p1["initiated_at"] + timedelta(minutes=rng.randint(1, 20))
            dup = self._create(orig["m"], t, "mobile_money", p1["amount"], orig["items"])
            p2 = dup["row"]
            # Confirmed in the same verification batch as the original.
            p2["confirmed_at"] = p1["confirmed_at"] + timedelta(minutes=rng.randint(1, 5))
            for a in dup["allocations"]:
                a["allocated_at"] = a["created_at"] = a["updated_at"] = p2["confirmed_at"]
            p2["payment_status"], p2["verified_by_id"] = "confirmed", p1["verified_by_id"]
            requested = rand_time(rng, next_weekday(p2["confirmed_at"].date() + timedelta(days=rng.randint(1, 4))),
                                  OFFICE_HOURS)
            processed = rand_time(rng, next_weekday(requested.date() + timedelta(days=rng.randint(2, 6))),
                                  OFFICE_HOURS)
            adj = self._refund(p2, p2["amount"], "Duplicate MoMo payment: dues sent twice. Second transfer refunded "
                                                 "to the sender's wallet.", requested, processed, hod)
            ctx.add("payment_allocation_adjustments", processed, payment_adjustment_id=adj["id"],
                    payment_allocation_id=dup["allocations"][0]["id"],
                    amount_reversed=dup["allocations"][0]["amount_allocated"],
                    created_by_id=ctx.ref["execs"][orig["m"]["session_idx"]]["Treasurer"]["id"])
            p2["payment_status"], p2["updated_at"] = "refunded", processed
            dup["refunded_at"] = processed

        for rec in picked[config.DUPLICATE_REFUNDS:]:
            p = rec["row"]
            excess = money(rng.choice([20, 30, 50]))
            p["amount"] = p["amount"] + excess
            p["notes"] = f"Student sent GHS {p['amount']} for GHS {p['amount'] - excess} dues; excess refunded."
            requested = rand_time(rng, next_weekday(p["confirmed_at"].date() + timedelta(days=1)), OFFICE_HOURS)
            processed = rand_time(rng, next_weekday(requested.date() + timedelta(days=rng.randint(1, 4))),
                                  OFFICE_HOURS)
            self._refund(p, excess, "Overpayment: amount sent exceeded dues assessed. Excess refunded to wallet.",
                         requested, processed, hod)
            p["payment_status"], p["updated_at"] = "partially_refunded", processed

    def _refund(self, payment, amount, reason, requested, processed, approver):
        m = next(r["m"] for r in self.records if r["row"] is payment)
        fin_sec = self.ctx.ref["execs"][m["session_idx"]]["Financial Secretary"]
        return self.ctx.add("payment_adjustments", requested, processed, payment_id=payment["id"],
                            adjustment_type="refund", amount=amount, reason=reason, adjustment_status="processed",
                            requested_by_id=fin_sec["id"], approved_by_id=approver["id"], processed_at=processed,
                            provider_reference=self._unique(lambda: ids.momo_transaction_id(self.rng)))

    # --- receipts ------------------------------------------------------------------------
    def receipts(self):
        ctx = self.ctx
        receipted = [r for r in self.records
                     if r["row"]["payment_status"] in ("confirmed", "refunded", "partially_refunded")]
        receipted.sort(key=lambda r: (r["row"]["confirmed_at"], r["row"]["id"]))
        seq = defaultdict(int)
        for r in receipted:
            p = r["row"]
            year = p["confirmed_at"].year
            seq[year] += 1
            number = ids.receipt_number(self.dept["code"], year, seq[year])
            issued = p["confirmed_at"] + timedelta(seconds=2)
            voided = p["payment_status"] == "refunded"
            r["receipt"] = ctx.add(
                "receipts", issued, r.get("refunded_at") if voided else issued, payment_id=p["id"],
                receipt_number=number, issued_at=issued, issued_by_id=p["verified_by_id"],
                receipt_status="voided" if voided else "issued",
                storage_key=f"receipts/{self.dept['code'].lower()}/{year}/{number}.pdf")


def _round5(value):
    return money(max(5, int(value / 5) * 5))

