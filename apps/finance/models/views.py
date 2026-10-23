from django.db import models

from apps.common.models import MoneyField


class DuesBalance(models.Model):
    """Read-only model over the v_dues_balances database view. Use for aggregate reporting."""

    assessment = models.OneToOneField(
        "finance.DuesAssessment",
        on_delete=models.DO_NOTHING,
        primary_key=True,
        db_column="assessment_id",
        related_name="balance_row",
    )
    department_membership = models.ForeignKey(
        "memberships.DepartmentMembership", on_delete=models.DO_NOTHING, related_name="+"
    )
    user = models.ForeignKey("accounts.User", on_delete=models.DO_NOTHING, related_name="+")
    department = models.ForeignKey("institutions.Department", on_delete=models.DO_NOTHING, related_name="+")
    academic_session = models.ForeignKey(
        "institutions.AcademicSession", on_delete=models.DO_NOTHING, related_name="+"
    )
    dues_type = models.ForeignKey("finance.DuesType", on_delete=models.DO_NOTHING, related_name="+")
    amount_assessed = MoneyField()
    amount_waived = MoneyField()
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2)
    balance = models.DecimalField(max_digits=14, decimal_places=2)
    assessment_state = models.CharField(max_length=20)
    due_date = models.DateField(null=True)

    class Meta:
        managed = False
        db_table = "v_dues_balances"

    def __str__(self):
        return f"{self.assessment_id}: {self.balance}"
