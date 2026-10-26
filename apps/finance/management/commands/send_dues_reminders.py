import datetime

from django.core.management.base import BaseCommand

from apps.finance.reminders import send_dues_reminders


class Command(BaseCommand):
    help = "Send due-soon, overdue and final dues reminders (each at most once per member and stage)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Count who would be reminded; send nothing."
        )
        parser.add_argument("--today", help="Pretend today is YYYY-MM-DD (for testing schedules).")

    def handle(self, *args, **options):
        today = datetime.date.fromisoformat(options["today"]) if options["today"] else None
        run = send_dues_reminders(today=today, dry_run=options["dry_run"])
        verb = "would be reminded" if options["dry_run"] else "reminded"
        self.stdout.write(
            f"{run.considered} unpaid assessments checked; {run.reminded_members} member(s) {verb}; "
            f"{run.notifications} notification(s) created."
        )
