from django.dispatch import Signal

# Sent after a payment becomes confirmed and its receipt is issued (inside the same transaction's
# on_commit, so receivers only run once the money is durably recorded). Args: payment.
payment_confirmed = Signal()

# Sent when a pending payment is rejected or fails verification. Args: payment, reason.
payment_rejected = Signal()

# Sent when a waiver request is approved or rejected. Args: waiver.
waiver_decided = Signal()

# Sent after a refund, reversal or correction is processed. Args: adjustment.
adjustment_processed = Signal()
