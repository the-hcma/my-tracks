"""Views for the Web UI application."""

import logging
import socket
from datetime import timedelta

import netifaces
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone as tz

from config.runtime import get_actual_mqtt_port, get_mqtt_port
from my_tracks.models import (CertificateAuthority, ClientCertificate,
                              Location, ServerCertificate)
from my_tracks.pki import (ALLOWED_KEY_SIZES, DEFAULT_CA_VALIDITY_DAYS,
                           DEFAULT_CERT_VALIDITY_DAYS, VALIDITY_PRESETS)
from my_tracks.pki import decrypt_private_key as pki_decrypt_private_key
from my_tracks.pki import encrypt_private_key as pki_encrypt_private_key
from my_tracks.pki import (generate_ca_certificate,
                           generate_client_certificate, generate_pkcs12,
                           generate_server_certificate, get_certificate_expiry,
                           get_certificate_fingerprint,
                           get_certificate_metadata, get_certificate_sans,
                           get_certificate_serial_number,
                           get_certificate_subject)

logger = logging.getLogger(__name__)


def get_all_local_ips() -> list[str]:
    """
    Get all non-loopback IPv4 addresses from broadcast-capable interfaces.

    Only includes addresses that have a broadcast address, which filters out
    VPN/tunnel interfaces (utun, tun, wg, ipsec) that use point-to-point links.

    Returns:
        Sorted list of IPv4 address strings (e.g., ['10.0.1.5', '192.168.1.10'])
    """
    ips: list[str] = []
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface)
        for addr_info in addrs.get(netifaces.AF_INET, []):
            ip = addr_info.get('addr', '')
            has_broadcast = bool(addr_info.get('broadcast'))
            if ip and not ip.startswith('127.') and has_broadcast:
                ips.append(ip)
    return sorted(set(ips))


def update_allowed_hosts(ips: list[str]) -> None:
    """
    Dynamically add discovered local IPs to ALLOWED_HOSTS.

    Only adds IPs that aren't already in the list. This ensures the server
    accepts requests on all its network interfaces without manual configuration.

    Args:
        ips: List of local IP addresses to allow
    """
    for ip in ips:
        if ip not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append(ip)
            logger.info("Added %s to ALLOWED_HOSTS", ip)


class NetworkState:
    """Holds network-related state for change detection."""

    last_known_ips: list[str] | None = None

    @classmethod
    def get_current_ips(cls) -> list[str]:
        """Get all current non-loopback IPv4 addresses."""
        return get_all_local_ips()

    @classmethod
    def get_current_ip(cls) -> str:
        """Get the primary local IP address (first detected)."""
        ips = cls.get_current_ips()
        return ips[0] if ips else "Unable to detect"

    @classmethod
    def check_and_update_ips(cls) -> tuple[list[str], bool]:
        """
        Check current IPs and detect if they changed.

        Also dynamically updates ALLOWED_HOSTS with any new IPs.

        Returns:
            Tuple of (current_ips, has_changed)
        """
        current_ips = cls.get_current_ips()
        has_changed = (
            cls.last_known_ips is not None and
            set(cls.last_known_ips) != set(current_ips)
        )

        if has_changed:
            logger.info("Network IPs changed: %s -> %s", cls.last_known_ips, current_ips)

        cls.last_known_ips = current_ips
        update_allowed_hosts(current_ips)
        return current_ips, has_changed

    @classmethod
    def check_and_update_ip(cls) -> tuple[str, bool]:
        """
        Check current IP and detect if it changed.

        Legacy wrapper that returns the primary IP.

        Returns:
            Tuple of (primary_ip, has_changed)
        """
        ips, changed = cls.check_and_update_ips()
        primary_ip = ips[0] if ips else "Unable to detect"
        return primary_ip, changed


def health(request: HttpRequest) -> JsonResponse:
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


@login_required
def network_info(request: HttpRequest) -> JsonResponse:
    """Return current network information for dynamic UI updates."""
    ips, _ = NetworkState.check_and_update_ips()
    hostname = socket.gethostname()
    server_port = request.META.get('SERVER_PORT', '8080')

    return JsonResponse({
        'hostname': hostname,
        'local_ip': ips[0] if ips else 'Unable to detect',
        'local_ips': ips,
        'port': int(server_port)
    })


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Home page with live map and activity log."""
    ips, _ = NetworkState.check_and_update_ips()
    primary_ip = ips[0] if ips else 'Unable to detect'
    hostname = socket.gethostname()

    # Get the actual port from the request (handles port 0 case correctly)
    server_port = request.META.get('SERVER_PORT', '8080')

    # Get coordinate precision from database schema
    # The Location model defines decimal_places for lat/lon fields
    # We use this to derive a sensible collapsing precision (~1 meter = 5 decimals)
    lat_field = Location._meta.get_field('latitude')
    db_decimal_places = lat_field.decimal_places or 10  # Default to 10 if not set
    # For collapsing, use 5 decimals (~1.1m precision) - derived from DB but practical
    # This avoids over-aggregation while still grouping GPS jitter
    collapse_precision = min(db_decimal_places, 5)

    # Get MQTT port (actual port if OS-allocated, else configured port)
    mqtt_configured_port = get_mqtt_port()
    mqtt_actual_port = get_actual_mqtt_port()
    mqtt_port = mqtt_actual_port if mqtt_actual_port is not None else mqtt_configured_port
    mqtt_enabled = mqtt_configured_port >= 0

    context = {
        'hostname': hostname,
        'local_ip': primary_ip,
        'local_ips': ips,
        'server_port': server_port,
        'collapse_precision': collapse_precision,
        'mqtt_port': mqtt_port,
        'mqtt_enabled': mqtt_enabled,
    }

    response = render(request, 'web_ui/home.html', context)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """User profile page for editing name, email, and password."""
    context: dict[str, object] = {}

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        user = request.user

        if form_type == 'profile':
            user.first_name = request.POST.get('first_name', '')
            user.last_name = request.POST.get('last_name', '')
            user.email = request.POST.get('email', '')
            user.save()
            context['profile_success'] = 'Profile updated successfully.'

        elif form_type == 'password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not user.check_password(current_password):
                context['password_error'] = 'Current password is incorrect.'
            elif new_password != confirm_password:
                context['password_error'] = 'New passwords do not match.'
            elif len(new_password) < 8:
                context['password_error'] = 'Password must be at least 8 characters.'
            else:
                try:
                    validate_password(new_password, user=user)
                    user.set_password(new_password)
                    user.save()
                    update_session_auth_hash(request, user)
                    context['password_success'] = 'Password changed successfully.'
                except ValidationError as e:
                    context['password_error'] = ' '.join(e.messages)

    active_cert = ClientCertificate.objects.filter(
        user=request.user, is_active=True, revoked=False
    ).select_related('issuing_ca').first()
    context['active_cert'] = active_cert
    if active_cert:
        context['cert_meta'] = get_certificate_metadata(
            active_cert.certificate_pem.encode()
        )

    active_ca = CertificateAuthority.objects.filter(is_active=True).first()
    context['active_ca'] = active_ca
    if active_ca:
        context['ca_meta'] = get_certificate_metadata(
            active_ca.certificate_pem.encode()
        )

    return render(request, 'web_ui/profile.html', context)


@login_required
def download_my_cert(request: HttpRequest) -> HttpResponse:
    """Download the authenticated user's client certificate as a PKCS#12 (.p12) bundle."""
    if request.method != 'POST':
        return HttpResponse(b'Method not allowed', status=405)

    cert = ClientCertificate.objects.select_related('issuing_ca').filter(
        user=request.user, is_active=True, revoked=False
    ).first()
    if cert is None:
        return HttpResponse(b'No active client certificate', status=404)

    password = (request.POST.get('p12_password') or '').strip()
    if not password:
        return HttpResponse(b'Password is required for .p12 export', status=400)

    client_key_pem = pki_decrypt_private_key(bytes(cert.encrypted_private_key))
    p12_bytes = generate_pkcs12(
        cert_pem=cert.certificate_pem.encode(),
        key_pem=client_key_pem,
        ca_cert_pem=cert.issuing_ca.certificate_pem.encode(),
        friendly_name=cert.common_name,
        password=password.encode(),
    )
    response = HttpResponse(p12_bytes, content_type='application/x-pkcs12')
    response['Content-Disposition'] = f'attachment; filename="{cert.common_name}.p12"'
    return response


@login_required
def download_ca_cert(request: HttpRequest) -> HttpResponse:
    """Download the active CA certificate PEM for OwnTracks configuration."""
    ca = CertificateAuthority.objects.filter(is_active=True).first()
    if ca is None:
        return HttpResponse(b'No active CA certificate', status=404)
    response = HttpResponse(ca.certificate_pem.encode(), content_type='application/x-pem-file')
    response['Content-Disposition'] = f'attachment; filename="{ca.common_name}.crt"'
    return response


@login_required
def about(request: HttpRequest) -> HttpResponse:
    """About & Setup page with server info and OwnTracks configuration."""
    ips, _ = NetworkState.check_and_update_ips()
    primary_ip = ips[0] if ips else 'Unable to detect'
    hostname = socket.gethostname()
    server_port = request.META.get('SERVER_PORT', '8080')

    mqtt_configured_port = get_mqtt_port()
    mqtt_actual_port = get_actual_mqtt_port()
    mqtt_port = mqtt_actual_port if mqtt_actual_port is not None else mqtt_configured_port
    mqtt_enabled = mqtt_configured_port >= 0

    context = {
        'hostname': hostname,
        'local_ip': primary_ip,
        'local_ips': ips,
        'server_port': server_port,
        'mqtt_port': mqtt_port,
        'mqtt_enabled': mqtt_enabled,
    }
    return render(request, 'web_ui/about.html', context)


def _is_staff(user: User) -> bool:  # type: ignore[override]
    """Check if user is staff (for use with user_passes_test decorator)."""
    return user.is_staff


@login_required
@user_passes_test(_is_staff, login_url='/')
def admin_panel(request: HttpRequest) -> HttpResponse:
    """Admin panel for user management."""
    context: dict[str, object] = {}

    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'create_user':
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            password = request.POST.get('password', '')
            is_admin = request.POST.get('is_admin') == 'on'

            if not username:
                context['create_error'] = 'Username is required.'
            elif not password:
                context['create_error'] = 'Password is required.'
            elif len(password) < 8:
                context['create_error'] = 'Password must be at least 8 characters.'
            elif User.objects.filter(username=username).exists():
                context['create_error'] = f"User '{username}' already exists."
            else:
                try:
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    if is_admin:
                        user.is_staff = True
                        user.is_superuser = True
                        user.save()
                    role = "administrator" if is_admin else "user"
                    context['create_success'] = f"User '{username}' created as {role}."
                except Exception as e:
                    context['create_error'] = str(e)

        if form_type == 'generate_ca':
            ca_cn_post = request.POST.get('ca_common_name')
            ca_cn = str(ca_cn_post).strip() if ca_cn_post is not None else 'My Tracks CA'
            ca_validity_raw = str(request.POST.get('ca_validity_days') or '3650')

            ca_key_size_raw = str(request.POST.get('ca_key_size') or '4096')

            if not ca_cn:
                context['ca_error'] = 'Common Name is required.'
            else:
                try:
                    validity_days = int(ca_validity_raw)
                    key_size = int(ca_key_size_raw)
                    if validity_days < 1 or validity_days > 36500:
                        context['ca_error'] = 'Validity must be between 1 and 36500 days.'
                    elif key_size not in ALLOWED_KEY_SIZES:
                        context['ca_error'] = f'Key size must be one of {ALLOWED_KEY_SIZES}.'
                    else:
                        cert_pem, key_pem = generate_ca_certificate(
                            common_name=ca_cn,
                            validity_days=validity_days,
                            key_size=key_size,
                        )
                        encrypted_key = pki_encrypt_private_key(key_pem)

                        CertificateAuthority.objects.filter(is_active=True).update(is_active=False)

                        CertificateAuthority.objects.create(
                            certificate_pem=cert_pem.decode(),
                            encrypted_private_key=encrypted_key,
                            common_name=get_certificate_subject(cert_pem),
                            fingerprint=get_certificate_fingerprint(cert_pem),
                            key_size=key_size,
                            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=validity_days),
                            not_valid_after=get_certificate_expiry(cert_pem),
                            is_active=True,
                        )
                        context['ca_success'] = f"CA '{ca_cn}' generated successfully."
                except ValueError:
                    context['ca_error'] = 'Validity days and key size must be a number.'
                except Exception as e:
                    context['ca_error'] = str(e)

        if form_type == 'expunge_ca':
            ca_id = request.POST.get('ca_id')
            try:
                ca = CertificateAuthority.objects.get(pk=ca_id)
                if ca.is_active:
                    context['ca_error'] = 'Cannot expunge an active CA. Deactivate it first.'
                else:
                    ca_name = ca.common_name
                    ca.delete()
                    context['ca_success'] = f"CA '{ca_name}' permanently deleted."
            except CertificateAuthority.DoesNotExist:
                context['ca_error'] = 'Certificate Authority not found.'

        if form_type == 'generate_server_cert':
            sc_cn_post = request.POST.get('sc_common_name')
            sc_cn = str(sc_cn_post).strip() if sc_cn_post is not None else ''
            sc_validity_raw = str(request.POST.get('sc_validity_days') or str(DEFAULT_CERT_VALIDITY_DAYS))
            sc_key_size_raw = str(request.POST.get('sc_key_size') or '4096')
            sc_sans_raw = str(request.POST.get('sc_san_entries') or '')
            sc_san_list = [s.strip() for s in sc_sans_raw.split(',') if s.strip()]

            active_ca_obj = CertificateAuthority.objects.filter(is_active=True).first()

            if not active_ca_obj:
                context['sc_error'] = 'No active CA certificate. Generate a CA first.'
            elif not sc_cn:
                context['sc_error'] = 'Common Name is required.'
            elif not sc_san_list:
                context['sc_error'] = 'At least one SAN entry is required.'
            else:
                try:
                    validity_days = int(sc_validity_raw)
                    key_size = int(sc_key_size_raw)
                    if validity_days < 1 or validity_days > 36500:
                        context['sc_error'] = 'Validity must be between 1 and 36500 days.'
                    elif key_size not in ALLOWED_KEY_SIZES:
                        context['sc_error'] = f'Key size must be one of {ALLOWED_KEY_SIZES}.'
                    else:
                        ca_key_pem = pki_decrypt_private_key(
                            bytes(active_ca_obj.encrypted_private_key)
                        )
                        cert_pem, srv_key_pem = generate_server_certificate(
                            ca_cert_pem=active_ca_obj.certificate_pem.encode(),
                            ca_key_pem=ca_key_pem,
                            common_name=sc_cn,
                            san_entries=sc_san_list,
                            validity_days=validity_days,
                            key_size=key_size,
                        )
                        encrypted_key = pki_encrypt_private_key(srv_key_pem)

                        ServerCertificate.objects.filter(is_active=True).update(is_active=False)

                        ServerCertificate.objects.create(
                            issuing_ca=active_ca_obj,
                            certificate_pem=cert_pem.decode(),
                            encrypted_private_key=encrypted_key,
                            common_name=get_certificate_subject(cert_pem),
                            fingerprint=get_certificate_fingerprint(cert_pem),
                            san_entries=get_certificate_sans(cert_pem),
                            key_size=key_size,
                            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=validity_days),
                            not_valid_after=get_certificate_expiry(cert_pem),
                            is_active=True,
                        )
                        context['sc_success'] = f"Server certificate '{sc_cn}' generated successfully."
                except ValueError:
                    context['sc_error'] = 'Validity days and key size must be a number.'
                except Exception as e:
                    context['sc_error'] = str(e)

        if form_type == 'expunge_server_cert':
            sc_id = request.POST.get('sc_id')
            try:
                sc = ServerCertificate.objects.get(pk=sc_id)
                if sc.is_active:
                    context['sc_error'] = 'Cannot expunge an active server certificate. Deactivate it first.'
                else:
                    sc_name = sc.common_name
                    sc.delete()
                    context['sc_success'] = f"Server certificate '{sc_name}' permanently deleted."
            except ServerCertificate.DoesNotExist:
                context['sc_error'] = 'Server certificate not found.'

        if form_type == 'issue_client_cert':
            cc_user_id_raw = request.POST.get('cc_user_id', '')
            cc_user_id = str(cc_user_id_raw).strip() if cc_user_id_raw else ''
            cc_validity_raw = str(request.POST.get('cc_validity_days') or str(DEFAULT_CERT_VALIDITY_DAYS))
            cc_key_size_raw = str(request.POST.get('cc_key_size') or '4096')

            active_ca_obj = CertificateAuthority.objects.filter(is_active=True).first()

            if not active_ca_obj:
                context['cc_error'] = 'No active CA certificate. Generate a CA first.'
            elif not cc_user_id:
                context['cc_error'] = 'Please select a user.'
            else:
                try:
                    target_user = User.objects.get(pk=int(cc_user_id))
                    validity_days = int(cc_validity_raw)
                    key_size = int(cc_key_size_raw)
                    if validity_days < 1 or validity_days > 36500:
                        context['cc_error'] = 'Validity must be between 1 and 36500 days.'
                    elif key_size not in ALLOWED_KEY_SIZES:
                        context['cc_error'] = f'Key size must be one of {ALLOWED_KEY_SIZES}.'
                    else:
                        ca_key_pem = pki_decrypt_private_key(
                            bytes(active_ca_obj.encrypted_private_key)
                        )
                        cert_pem, client_key_pem = generate_client_certificate(
                            ca_cert_pem=active_ca_obj.certificate_pem.encode(),
                            ca_key_pem=ca_key_pem,
                            username=str(target_user.username),
                            validity_days=validity_days,
                            key_size=key_size,
                        )
                        encrypted_key = pki_encrypt_private_key(client_key_pem)

                        ClientCertificate.objects.filter(
                            user=target_user, is_active=True
                        ).update(is_active=False)

                        serial = get_certificate_serial_number(cert_pem)

                        ClientCertificate.objects.create(
                            user=target_user,
                            issuing_ca=active_ca_obj,
                            certificate_pem=cert_pem.decode(),
                            encrypted_private_key=encrypted_key,
                            common_name=get_certificate_subject(cert_pem),
                            fingerprint=get_certificate_fingerprint(cert_pem),
                            serial_number=hex(serial),
                            key_size=key_size,
                            not_valid_before=get_certificate_expiry(cert_pem) - timedelta(days=validity_days),
                            not_valid_after=get_certificate_expiry(cert_pem),
                            is_active=True,
                        )
                        context['cc_success'] = f"Client certificate issued for '{target_user.username}'."
                except User.DoesNotExist:
                    context['cc_error'] = 'Selected user not found.'
                except ValueError:
                    context['cc_error'] = 'Validity days and key size must be a number.'
                except Exception as e:
                    context['cc_error'] = str(e)

        if form_type == 'revoke_client_cert':
            cc_id = request.POST.get('cc_id')
            try:
                cc = ClientCertificate.objects.get(pk=cc_id)
                if cc.revoked:
                    context['cc_error'] = f"Certificate for '{cc.common_name}' is already revoked."
                else:
                    cc.revoked = True
                    cc.is_active = False
                    cc.revoked_at = tz.now()
                    cc.save()
                    context['cc_success'] = f"Certificate for '{cc.common_name}' revoked."
            except ClientCertificate.DoesNotExist:
                context['cc_error'] = 'Client certificate not found.'

        if form_type == 'expunge_client_cert':
            cc_id = request.POST.get('cc_id')
            try:
                cc = ClientCertificate.objects.get(pk=cc_id)
                if cc.is_active and not cc.revoked:
                    context['cc_error'] = 'Cannot expunge an active certificate. Revoke it first.'
                else:
                    cc_name = cc.common_name
                    cc.delete()
                    context['cc_success'] = f"Certificate for '{cc_name}' permanently deleted."
            except ClientCertificate.DoesNotExist:
                context['cc_error'] = 'Client certificate not found.'

    users = list(User.objects.all().order_by('username'))
    user_id_to_active_cert = {
        cc.user_id: cc
        for cc in ClientCertificate.objects.filter(is_active=True, revoked=False)
    }
    for u in users:
        u.active_cert = user_id_to_active_cert.get(u.pk)  # type: ignore[attr-defined]
    context['users'] = users

    active_ca = CertificateAuthority.objects.filter(is_active=True).first()
    context['active_ca'] = active_ca
    if active_ca:
        context['active_ca_meta'] = get_certificate_metadata(
            active_ca.certificate_pem.encode()
        )
    context['ca_history'] = list(CertificateAuthority.objects.all()[:10])

    active_sc = ServerCertificate.objects.filter(is_active=True).first()
    context['active_sc'] = active_sc
    if active_sc:
        context['active_sc_meta'] = get_certificate_metadata(
            active_sc.certificate_pem.encode()
        )
    context['sc_history'] = list(ServerCertificate.objects.all()[:10])

    context['client_certs'] = list(
        ClientCertificate.objects.select_related('user', 'issuing_ca').all()[:50]
    )
    context['revoked_certs'] = list(
        ClientCertificate.objects.filter(revoked=True)
        .select_related('user')
        .order_by('-revoked_at')[:50]
    )

    context['validity_presets'] = VALIDITY_PRESETS
    context['default_cert_validity'] = DEFAULT_CERT_VALIDITY_DAYS
    context['default_ca_validity'] = DEFAULT_CA_VALIDITY_DAYS

    pki_has_message = any(context.get(k) for k in (
        'ca_success', 'ca_error', 'sc_success', 'sc_error', 'cc_success', 'cc_error',
    ))
    context['active_tab'] = 'pki' if pki_has_message else 'users'

    ips = get_all_local_ips()
    hostname = socket.gethostname()
    san_candidates: list[str] = list(ips)
    san_candidates.append(hostname)
    request_host = request.get_host().split(":")[0]
    if request_host and request_host not in san_candidates:
        san_candidates.append(request_host)
    context['default_san_list'] = san_candidates
    context['default_sans'] = ', '.join(san_candidates)
    context['hostname'] = hostname

    return render(request, 'web_ui/admin_panel.html', context)
