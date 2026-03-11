"""Re-encrypt PKI private keys from an old SECRET_KEY to the current one."""
from cryptography.fernet import InvalidToken
from django.core.management.base import BaseCommand, CommandError

from my_tracks.models import (CertificateAuthority, ClientCertificate,
                              ServerCertificate)
from my_tracks.pki import reencrypt_private_key

_PKI_MODELS = (CertificateAuthority, ServerCertificate, ClientCertificate)


class Command(BaseCommand):
    help = "Re-encrypt all PKI private keys from an old SECRET_KEY to the current SECRET_KEY."

    def add_arguments(self, parser: "BaseCommand") -> None:  # type: ignore[override]
        parser.add_argument(
            "--old-secret-key",
            required=True,
            help="The old SECRET_KEY used to encrypt the existing private keys.",
        )

    def _probe_key(self, old_key: str) -> bool:
        """Try decrypting the first PKI key found; return True on success."""
        for model in _PKI_MODELS:
            obj = model.objects.exclude(encrypted_private_key=b"").first()
            if obj is not None:
                try:
                    reencrypt_private_key(bytes(obj.encrypted_private_key), old_key)
                    return True
                except InvalidToken:
                    return False
        return True

    def handle(self, *args: object, **options: object) -> None:
        old_key = str(options["old_secret_key"])
        if not old_key:
            raise CommandError("--old-secret-key must not be empty")

        if not self._probe_key(old_key):
            raise CommandError(
                "The provided --old-secret-key cannot decrypt the existing PKI keys.\n"
                "  The key must match the SECRET_KEY that was active when the PKI\n"
                "  certificates were originally created.\n\n"
                "  Common causes:\n"
                "    • .env has a placeholder SECRET_KEY that was never used by Django\n"
                "    • PKI keys were created with the Django default:\n"
                "        django-insecure-change-me-in-production\n"
                "    • SECRET_KEY was rotated after PKI keys were generated\n\n"
                "  To find the correct key, check:\n"
                "    1. The .env file that was active when PKI certs were created\n"
                "    2. Django's default in config/settings.py (used when .env has no SECRET_KEY)\n"
                "    3. Any environment variable overrides"
            )

        total = 0
        for model in _PKI_MODELS:
            queryset = model.objects.exclude(encrypted_private_key=b"")
            count = 0
            for obj in queryset:
                obj.encrypted_private_key = reencrypt_private_key(
                    bytes(obj.encrypted_private_key), old_key
                )
                obj.save(update_fields=["encrypted_private_key"])
                count += 1
            if count:
                self.stdout.write(f"  Re-encrypted {count} {model.__name__} key(s)")
            total += count

        if total:
            self.stdout.write(self.style.SUCCESS(f"Done — {total} private key(s) re-encrypted."))
        else:
            self.stdout.write("No PKI private keys found to re-encrypt.")
