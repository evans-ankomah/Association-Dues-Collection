from django.db import migrations

RECEIVED = "('confirmed', 'partially_refunded', 'refunded')"

CREATE_VIEW = f"""
CREATE VIEW v_dues_balances AS
SELECT
    a.id                         AS assessment_id,
    a.department_membership_id,
    m.user_id,
    m.department_id,
    m.academic_session_id,
    a.dues_type_id,
    a.amount_assessed,
    a.amount_waived,
    COALESCE(al.total, 0) - COALESCE(rv.total, 0) AS amount_paid,
    CASE WHEN a.assessment_state = 'cancelled' THEN 0
         ELSE a.amount_assessed - a.amount_waived - (COALESCE(al.total, 0) - COALESCE(rv.total, 0))
    END                          AS balance,
    a.assessment_state,
    a.due_date
FROM dues_assessments a
JOIN department_memberships m ON m.id = a.department_membership_id
LEFT JOIN (
    SELECT pa.dues_assessment_id, SUM(pa.amount_allocated) AS total
    FROM payment_allocations pa
    JOIN payments p ON p.id = pa.payment_id
    WHERE p.payment_status IN {RECEIVED}
    GROUP BY pa.dues_assessment_id
) al ON al.dues_assessment_id = a.id
LEFT JOIN (
    SELECT pa.dues_assessment_id, SUM(x.amount_reversed) AS total
    FROM payment_allocation_adjustments x
    JOIN payment_adjustments j ON j.id = x.payment_adjustment_id
    JOIN payment_allocations pa ON pa.id = x.payment_allocation_id
    JOIN payments p ON p.id = pa.payment_id
    WHERE j.adjustment_status = 'processed' AND p.payment_status IN {RECEIVED}
    GROUP BY pa.dues_assessment_id
) rv ON rv.dues_assessment_id = a.id;
"""


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [migrations.RunSQL(CREATE_VIEW, "DROP VIEW IF EXISTS v_dues_balances;")]
