"""
Create the admin superuser from environment variables.

Exists so the project can be fully bootstrapped without shell access —
useful when deploying from a phone, or in any environment where you
can set variables but can't open an interactive terminal.

Reads:
  ADMIN_USERNAME  (default: admin)
  ADMIN_EMAIL     (default: admin@example.com)
  ADMIN_PASSWORD  (required — command exits without creating if unset)

Safe to run repeatedly: if the user already exists it does nothing.
Called automatically by start.sh on every deploy.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create a superuser from ADMIN_* environment variables (idempotent)."

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get("ADMIN_USERNAME", "admin")
        email = os.environ.get("ADMIN_EMAIL", "admin@example.com")
        password = os.environ.get("ADMIN_PASSWORD")

        if not password:
            self.stdout.write(self.style.WARNING(
                "  ADMIN_PASSWORD not set — skipping superuser creation. "
                "Set it in your service variables to enable admin login."
            ))
            return

        if len(password) < 12:
            self.stdout.write(self.style.ERROR(
                "  ADMIN_PASSWORD is shorter than 12 characters. "
                "Refusing to create an admin account with a weak password."
            ))
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.SUCCESS(
                f"  Superuser '{username}' already exists — nothing to do."
            ))
            return

        User.objects.create_superuser(
            username=username, email=email, password=password
        )
        self.stdout.write(self.style.SUCCESS(
            f"  ✓ Created superuser '{username}'"
        ))
