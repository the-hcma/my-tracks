"""Re-encrypt PKI private keys from an old SECRET_KEY to the current one."""
from django.core.management.base import BaseCommand, CommandError

from my_tracks.models import (CertificateAuthority, ClientCertificate,
                              ServerCertificate)
from my_tracks.pki import reencrypt_private_key


class Command(BaseCommand):
    help = "Re-encrypt all PKI private keys from an old SECRET_KEY to the current SECRET_KEY."

    def add_arguments(self, parser: "BaseCommand") -> None:  # type: ignore[override]
        parser.add_argument(
            "--old-secret-key",
            required=True,
            help="The old SECRET_KEY used to encrypt the existing private keys.",
        )

    def handle(self, *args: object, **options: object) -> None:
        old_key = str(options["old_secret_key"])
        if not old_key:
            raise CommandError("--old-secret-key must not be empty")

        total = 0
        for model in (CertificateAuthority, ServerCertificate, ClientCertificate):
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
