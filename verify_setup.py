#!/usr/bin/env python3
"""
Verification script for OwnTracks Django Backend setup.

This script verifies that the installation is complete and correct,
checking all necessary files, dependencies, and configurations.
"""

import sys
from pathlib import Path


class SetupVerifier:
    """Verify Django project setup."""

    def __init__(self) -> None:
        """Initialize verifier."""
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.success: list[str] = []

    def check_file_exists(self, filepath: str, required: bool = True) -> bool:
        """Check if a file exists."""
        path = Path(filepath)
        if path.exists():
            self.success.append(f"✓ Found {filepath}")
            return True
        else:
            if required:
                self.errors.append(f"✗ Missing required file: {filepath}")
            else:
                self.warnings.append(f"⚠ Missing optional file: {filepath}")
            return False

    def check_directory_exists(self, dirpath: str) -> bool:
        """Check if a directory exists."""
        path = Path(dirpath)
        if path.exists() and path.is_dir():
            self.success.append(f"✓ Found directory {dirpath}")
            return True
        else:
            self.errors.append(f"✗ Missing directory: {dirpath}")
            return False

    def verify_project_structure(self) -> None:
        """Verify project directory structure."""
        print("Checking project structure...")

        # Root files
        self.check_file_exists("manage.py")
        self.check_file_exists("pyproject.toml")
        self.check_file_exists("README.md")
        self.check_file_exists(".env.example")
        self.check_file_exists(".gitignore")

        # Documentation
        self.check_file_exists("QUICKSTART.md")
        self.check_file_exists("API.md")
        self.check_file_exists("DEPLOYMENT.md")
        self.check_file_exists("PROJECT_SUMMARY.md")

        # Django project directory
        self.check_directory_exists("mytracks")
        self.check_file_exists("mytracks/__init__.py")
        self.check_file_exists("mytracks/settings.py")
        self.check_file_exists("mytracks/urls.py")
        self.check_file_exists("mytracks/wsgi.py")
        self.check_file_exists("mytracks/asgi.py")

        # Tracker app directory
        self.check_directory_exists("tracker")
        self.check_file_exists("tracker/__init__.py")
        self.check_file_exists("tracker/models.py")
        self.check_file_exists("tracker/serializers.py")
        self.check_file_exists("tracker/views.py")
        self.check_file_exists("tracker/urls.py")
        self.check_file_exists("tracker/admin.py")
        self.check_file_exists("tracker/apps.py")

        # Migrations
        self.check_directory_exists("tracker/migrations")
        self.check_file_exists("tracker/migrations/__init__.py")

        # Optional files
        self.check_file_exists(".env", required=False)
        self.check_file_exists("db.sqlite3", required=False)

    def verify_python_version(self) -> None:
        """Verify Python version is 3.12+."""
        print("\nChecking Python version...")
        version = sys.version_info

        if version.major == 3 and version.minor >= 12:
            self.success.append(f"✓ Python {version.major}.{version.minor}.{version.micro}")
        else:
            self.errors.append(
                f"✗ Python 3.12+ required, found {version.major}.{version.minor}.{version.micro}"
            )

    def verify_dependencies(self) -> None:
        """Verify key dependencies can be imported."""
        print("\nChecking dependencies...")

        dependencies = [
            ("django", "Django"),
            ("rest_framework", "Django REST Framework"),
            ("decouple", "python-decouple"),
        ]

        for module_name, display_name in dependencies:
            try:
                __import__(module_name)
                self.success.append(f"✓ {display_name} installed")
            except ImportError:
                self.warnings.append(
                    f"⚠ {display_name} not installed (run: uv pip install -e .)"
                )

    def verify_django_setup(self) -> None:
        """Verify Django can be initialized."""
        print("\nChecking Django setup...")

        try:
            import django
            from django.conf import settings

            # Try to setup Django
            import os
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mytracks.settings')
            django.setup()

            self.success.append("✓ Django configured correctly")

            # Check if migrations are needed
            from django.core.management import call_command
            from io import StringIO

            out = StringIO()
            call_command('showmigrations', '--plan', stdout=out, no_color=True)
            output = out.getvalue()

            if '[ ]' in output:
                self.warnings.append("⚠ Pending migrations (run: python manage.py migrate)")
            else:
                self.success.append("✓ All migrations applied")

        except Exception as e:
            self.errors.append(f"✗ Django setup failed: {e}")

    def print_report(self) -> bool:
        """Print verification report and return success status."""
        print("\n" + "=" * 60)
        print("SETUP VERIFICATION REPORT")
        print("=" * 60)

        if self.success:
            print(f"\n✅ SUCCESS ({len(self.success)} checks passed)")
            for msg in self.success[:5]:  # Show first 5
                print(f"  {msg}")
            if len(self.success) > 5:
                print(f"  ... and {len(self.success) - 5} more")

        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)})")
            for msg in self.warnings:
                print(f"  {msg}")

        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)})")
            for msg in self.errors:
                print(f"  {msg}")

        print("\n" + "=" * 60)

        if self.errors:
            print("\n❌ Setup verification FAILED")
            print("Please fix the errors above and run again.")
            return False
        elif self.warnings:
            print("\n⚠️  Setup verification completed with warnings")
            print("The project should work, but check warnings above.")
            return True
        else:
            print("\n✅ Setup verification PASSED")
            print("Your OwnTracks Django Backend is ready to use!")
            print("\nNext steps:")
            print("1. Copy .env.example to .env and configure")
            print("2. Run: python manage.py migrate")
            print("3. Run: python manage.py createsuperuser")
            print("4. Run: python manage.py runserver")
            return True

    def run(self) -> bool:
        """Run all verification checks."""
        print("OwnTracks Django Backend - Setup Verification")
        print("=" * 60)

        self.verify_python_version()
        self.verify_project_structure()
        self.verify_dependencies()

        # Only check Django if basic structure is in place
        if not self.errors:
            self.verify_django_setup()

        return self.print_report()


def main() -> None:
    """Main entry point."""
    verifier = SetupVerifier()
    success = verifier.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
