from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.common import seeding

DEFAULT_DIR = Path(settings.BASE_DIR) / "seed" / "output" / "json"


class Command(BaseCommand):
    help = "Load the anonymised UMaT sample dataset. Development and demo use only."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(DEFAULT_DIR), help="Folder containing the seed JSON files.")
        parser.add_argument(
            "--password",
            default="depthub-demo-2026",
            help="Password given to every seeded account (default: depthub-demo-2026).",
        )
        parser.add_argument("--flush", action="store_true", help="Delete existing DeptHub data first.")
        parser.add_argument(
            "--allow-non-debug",
            action="store_true",
            help="Allow running when DEBUG is off. Never use against production.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_non_debug"]:
            raise CommandError("Refusing to load sample data with DEBUG off. Pass --allow-non-debug if sure.")
        seed_dir = Path(options["dir"])
        if not (seed_dir / "users.json").exists():
            raise CommandError(f"No seed data in {seed_dir}. Generate it first: python seed/generate_umat.py")

        if options["flush"]:
            seeding.flush()
            self.stdout.write("Flushed existing data.")
        elif User.objects.exists():
            raise CommandError("The database already has users. Re-run with --flush to replace them.")

        report = seeding.load(seed_dir, options["password"])

        for table, count in report.loaded.items():
            self.stdout.write(f"  {table:<32} {count:>6}")
        total = sum(report.loaded.values())
        self.stdout.write(self.style.SUCCESS(f"Loaded {total} rows into {len(report.loaded)} tables."))
        if report.skipped_tables:
            self.stdout.write(f"Not loaded yet (no model): {', '.join(report.skipped_tables)}")
        for table, cols in report.dropped_columns.items():
            self.stdout.write(self.style.WARNING(f"Ignored columns in {table}: {', '.join(sorted(cols))}"))
        self.stdout.write(
            self.style.WARNING(
                "Sample phone numbers use real Ghanaian prefixes. Keep SMS_BACKEND=disabled with this data."
            )
        )
        self.stdout.write(f"Every account's password is: {options['password']}")
