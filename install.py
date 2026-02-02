#!/usr/bin/env python3
"""
Installation script for OwnTracks Django Backend.

This script automates the setup process by:
1. Creating necessary directories
2. Extracting all project files from PROJECT_FILES.txt
3. Setting up the virtual environment
4. Installing dependencies
"""

import os
import sys
from pathlib import Path


def create_file(filepath: str, content: str) -> None:
    """Create a file with the given content."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"✓ Created {filepath}")


def main() -> None:
    """Run the installation process."""
    print("=" * 60)
    print("OwnTracks Django Backend - Installation Script")
    print("=" * 60)
    print()

    # Check if PROJECT_FILES.txt exists
    project_files = Path("PROJECT_FILES.txt")
    if not project_files.exists():
        print("❌ Error: PROJECT_FILES.txt not found!")
        print("Please ensure you're running this script from the project root.")
        sys.exit(1)

    print("📁 Creating project structure...")

    # Read PROJECT_FILES.txt and extract file contents
    content = project_files.read_text()

    # Split by file markers
    files = {}
    current_file = None
    current_content = []

    for line in content.split('\n'):
        if line.startswith('# ===== ') and line.endswith(' ====='):
            # Save previous file
            if current_file:
                files[current_file] = '\n'.join(current_content)
            # Start new file
            current_file = line.replace('# ===== ', '').replace(' =====', '').strip()
            current_content = []
        elif current_file:
            current_content.append(line)

    # Save last file
    if current_file:
        files[current_file] = '\n'.join(current_content)

    # Create all files
    for filepath, file_content in files.items():
        if filepath and file_content.strip():
            create_file(filepath, file_content.strip() + '\n')

    print()
    print("✅ Project structure created successfully!")
    print()
    print("Next steps:")
    print("1. Copy .env.example to .env and configure your settings")
    print("2. Run: uv venv")
    print("3. Run: source .venv/bin/activate")
    print("4. Run: uv pip install -e .")
    print("5. Run: python manage.py migrate")
    print("6. Run: python manage.py createsuperuser")
    print("7. Run: python manage.py runserver")
    print()
    print("=" * 60)


if __name__ == '__main__':
    main()
