"""Views for the Web UI application."""

import logging
import os
from dataclasses import dataclass, field
from datetime import timedelta

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import (
    UserAttributeSimilarityValidator, get_password_validators,
    validate_password)
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as tz

from app.apps import get_mqtt_broker
from app.models import (CertificateAuthority, ClientCertificate, Device,
                        Location, ServerCertificate, SmtpConfig, Transition,
                        TransitionAction, UserProfile, Waypoint)
from app.mqtt.commands import CommandPublisher
from app.notifications import (get_smtp_backend, send_test_email,
                               smtp_friendly_error)
from app.pki import (ALLOWED_KEY_SIZES, DEFAULT_CA_VALIDITY_DAYS,
                     DEFAULT_CERT_VALIDITY_DAYS, VALIDITY_PRESETS)
from app.pki import decrypt_private_key as pki_decrypt_private_key
from app.pki import encrypt_private_key as pki_encrypt_private_key
from app.pki import (generate_ca_certificate, generate_client_certificate,
                     generate_pkcs12, generate_server_certificate,
                     get_certificate_expiry, get_certificate_fingerprint,
                     get_certificate_metadata, get_certificate_sans,
                     get_certificate_serial_number, get_certificate_subject)
from app.utils import get_version
from config.runtime import (get_actual_mqtt_port, get_mqtt_port,
                            get_mqtt_tls_port)

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset(('localhost', '127.0.0.1', '::1'))


def get_all_local_ips() -> list[str]:
    """
    Get all non-loopback IPv4 addresses from broadcast-capable interfaces.

    Only includes addresses that have a broadcast address, which filters out
    VPN/tunnel interfaces (utun, tun, wg, ipsec) that use point-to-point links.

    Returns:
        Sorted list of IPv4 address strings (e.g., ['10.0.1.5', '192.168.1.10'])
    """
    try:
        import netifaces
    except ImportError:
        return []
    ips: list[str] = []
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface)
        for addr_info in addrs.get(netifaces.AF_INET, []):
            ip = addr_info.get('addr', '')
            has_broadcast = bool(addr_info.get('broadcast'))
            if ip and not ip.startswith('127.') and has_broadcast:
                ips.append(ip)
    return sorted(set(ips))


@dataclass
class ServerInfo:
    """Externally-visible server connection information."""

    hostname: str
    port: str
    scheme: str
    accessible_hosts: list[str] = field(default_factory=list)
    lan_ips: list[str] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        default_port = '443' if self.scheme == 'https' else '80'
        host_part = self.hostname
        if self.port != default_port:
            host_part = f'{self.hostname}:{self.port}'
        return f'{self.scheme}://{host_part}'

    def url_for_host(self, host: str) -> str:
        default_port = '443' if self.scheme == 'https' else '80'
        if self.port != default_port:
            return f'{self.scheme}://{host}:{self.port}'
        return f'{self.scheme}://{host}'


def get_server_info(request: HttpRequest) -> ServerInfo:
    """
    Derive externally-visible server info from the incoming request.

    Behind a reverse proxy (nginx) with Docker port mapping, the Host header
    carries the hostname but not the external port (nginx sees its internal
    port, not the Docker-mapped one).  HTTPS_PORT from the environment
    provides the externally-visible port in that scenario.
    """
    request_host = request.get_host()
    if ':' in request_host:
        hostname, port = request_host.rsplit(':', 1)
    else:
        hostname = request_host
        port = '443' if request.is_secure() else '80'

    env_port = os.environ.get('HTTPS_PORT') if request.is_secure() else os.environ.get('HTTP_PORT')
    if env_port:
        port = env_port

    scheme = 'https' if request.is_secure() else 'http'

    hosts: set[str] = set()
    for h in settings.ALLOWED_HOSTS:
        if h and h != '*':
            hosts.add(h)

    lan_ips = get_all_local_ips()
    hosts.update(lan_ips)

    hosts.discard(hostname)

    primary_is_real = hostname not in _LOOPBACK_HOSTS
    if primary_is_real:
        accessible = sorted(h for h in hosts if h not in _LOOPBACK_HOSTS)
    else:
        accessible = sorted(hosts)

    return ServerInfo(
        hostname=hostname,
        port=port,
        scheme=scheme,
        accessible_hosts=accessible,
        lan_ips=lan_ips,
    )


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


class FirstRunLoginView(LoginView):
    """Login view that adds a first-run setup banner when no admin users exist."""

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context['no_admin'] = not User.objects.filter(is_staff=True).exists()
        return context


@login_required
def network_info(request: HttpRequest) -> JsonResponse:
    """Return current network information for dynamic UI updates."""
    info = get_server_info(request)

    return JsonResponse({
        'hostname': info.hostname,
        'local_ip': info.hostname,
        'local_ips': info.accessible_hosts,
        'port': int(info.port),
        'scheme': info.scheme,
        'server_url': info.base_url,
    })


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Home page with live map and activity log."""
    info = get_server_info(request)

    lat_field = Location._meta.get_field('latitude')
    db_decimal_places = lat_field.decimal_places or 10
    collapse_precision = min(db_decimal_places, 5)

    mqtt_configured_port = get_mqtt_port()
    mqtt_actual_port = get_actual_mqtt_port()
    mqtt_port = mqtt_actual_port if mqtt_actual_port is not None else mqtt_configured_port
    mqtt_enabled = mqtt_configured_port >= 0

    context = {
        'hostname': info.hostname,
        'local_ip': info.hostname,
        'local_ips': info.accessible_hosts,
        'server_port': info.port,
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
    """User profile page for editing name, email, password, and home location."""
    context: dict[str, object] = {}
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        user = request.user

        if form_type == 'home_location':
            lat_str = (request.POST.get('home_latitude') or '').strip()
            lon_str = (request.POST.get('home_longitude') or '').strip()
            label = (request.POST.get('home_label') or '').strip() or 'Home'
            try:
                lat = float(lat_str) if lat_str else None
                lon = float(lon_str) if lon_str else None
                if (lat is None) != (lon is None):
                    raise ValueError("Both latitude and longitude are required")
                if lat is not None and not (-90 <= lat <= 90):
                    raise ValueError("Latitude must be between -90 and 90")
                if lon is not None and not (-180 <= lon <= 180):
                    raise ValueError("Longitude must be between -180 and 180")
                user_profile.home_latitude = lat  # type: ignore[assignment]
                user_profile.home_longitude = lon  # type: ignore[assignment]
                user_profile.home_label = label
                user_profile.save(update_fields=['home_latitude', 'home_longitude', 'home_label'])
                context['home_location_success'] = 'Home location saved.'
            except ValueError as e:
                context['home_location_error'] = str(e)

        elif form_type == 'profile':
            user.first_name = request.POST.get('first_name', '')
            user.last_name = request.POST.get('last_name', '')
            user.email = request.POST.get('email', '')
            user.save()
            context['profile_success'] = 'Profile updated successfully.'

        elif form_type == 'password':
            current_password = str(request.POST.get('current_password', ''))
            new_password = str(request.POST.get('new_password', ''))
            confirm_password = str(request.POST.get('confirm_password', ''))
            bypass_similarity = request.POST.get('bypass_similarity_check') == '1'

            if not user.check_password(current_password):
                context['password_error'] = 'Current password is incorrect.'
            elif new_password != confirm_password:
                context['password_error'] = 'New passwords do not match.'
            elif len(new_password) < 8:
                context['password_error'] = 'Password must be at least 8 characters.'
            else:
                try:
                    if bypass_similarity:
                        validators = [
                            v for v in get_password_validators(settings.AUTH_PASSWORD_VALIDATORS)
                            if not isinstance(v, UserAttributeSimilarityValidator)
                        ]
                        validate_password(new_password, user=user, password_validators=validators)
                    else:
                        validate_password(new_password, user=user)
                    user.set_password(new_password)
                    user.save()
                    update_session_auth_hash(request, user)
                    logger.info("[http] User '%s' changed their password", user.username)
                    context['password_success'] = 'Password changed successfully.'
                except ValidationError as e:
                    context['password_error'] = ' '.join(str(m) for m in e.messages)

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

    # My Devices — paired with their client certificate (matched by common_name == device_id)
    raw_devices = Device.objects.filter(owner=request.user).order_by('-last_seen')
    cert_map = {
        c.common_name: c
        for c in ClientCertificate.objects.filter(
            user=request.user,
            common_name__in=[d.device_id for d in raw_devices],
        ).select_related('issuing_ca')
    }
    context['devices_with_certs'] = [
        {'device': d, 'cert': cert_map.get(d.device_id)}
        for d in raw_devices
    ]

    # Home location
    context['user_profile'] = user_profile
    last_location = (
        Location.objects
        .filter(device__owner=request.user)
        .order_by('-timestamp')
        .first()
    )
    context['last_location'] = last_location

    # Geofences tab data
    context['waypoints'] = list(
        Waypoint.objects
        .filter(user=request.user, is_active=True)
        .order_by('label')
    )
    context['geofence_devices'] = list(
        Device.objects.filter(owner=request.user).order_by('name')
    )
    context['transitions'] = list(
        Transition.objects
        .filter(device__owner=request.user)
        .select_related('waypoint', 'device')
        .order_by('-timestamp')[:50]
    )
    context['actions'] = list(
        TransitionAction.objects
        .filter(user=request.user)
        .select_related('waypoint')
        .order_by('waypoint__label', 'event')
    )
    context['smtp_configured'] = SmtpConfig.get() is not None

    return render(request, 'web_ui/profile.html', context)


@login_required
def geofences(request: HttpRequest) -> HttpResponse:
    """Geofence management: create, edit, delete waypoints, sync to device."""
    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'add_waypoint':
            Waypoint.objects.create(
                user=request.user,
                label=(request.POST.get('label') or '').strip() or 'Unnamed',
                latitude=float(str(request.POST.get('latitude') or '0')),
                longitude=float(str(request.POST.get('longitude') or '0')),
                radius=int(str(request.POST.get('radius') or 100)),
            )

        elif form_type == 'edit_waypoint':
            wp = get_object_or_404(
                Waypoint, pk=request.POST['waypoint_id'], user=request.user
            )
            wp.label = (request.POST.get('label') or '').strip() or wp.label
            wp.latitude = float(  # type: ignore[assignment]
                str(request.POST.get('latitude') or wp.latitude)
            )
            wp.longitude = float(  # type: ignore[assignment]
                str(request.POST.get('longitude') or wp.longitude)
            )
            wp.radius = int(str(request.POST.get('radius') or wp.radius))
            wp.save()

        elif form_type == 'delete_waypoint':
            wp = get_object_or_404(
                Waypoint, pk=request.POST['waypoint_id'], user=request.user
            )
            wp.delete()

        elif form_type == 'sync_to_device':
            device = get_object_or_404(
                Device, pk=request.POST['device_id'], owner=request.user
            )
            active_waypoints = list(
                Waypoint.objects.filter(user=request.user, is_active=True)
            )
            payload = [
                {
                    'desc': w.label,
                    'lat': float(w.latitude),
                    'lon': float(w.longitude),
                    'rad': w.radius,
                    'tst': int(w.updated_at.timestamp()),
                }
                for w in active_waypoints
            ]
            mqtt_device_id = f"{device.mqtt_user}/{device.device_id}"
            broker = get_mqtt_broker()
            publisher = (
                CommandPublisher(mqtt_client=broker.amqtt_broker)
                if broker is not None and broker.is_running
                else CommandPublisher()
            )
            async_to_sync(publisher.set_waypoints)(mqtt_device_id, payload, owner=request.user.username)

        elif form_type == 'add_action':
            wp_id_raw = (request.POST.get('waypoint_id') or '').strip()
            event = (request.POST.get('event') or 'any').strip()
            email = (request.POST.get('email_address') or '').strip()
            if email and event in ('enter', 'leave', 'any'):
                waypoint: Waypoint | None = None
                if wp_id_raw:
                    waypoint = get_object_or_404(Waypoint, pk=wp_id_raw, user=request.user)
                TransitionAction.objects.create(
                    user=request.user,
                    waypoint=waypoint,
                    event=event,
                    action_type=TransitionAction.ACTION_EMAIL,
                    email_address=email,
                )

        elif form_type == 'delete_action':
            action = get_object_or_404(
                TransitionAction, pk=request.POST['action_id'], user=request.user
            )
            action.delete()

        next_url = (request.POST.get('next_url') or '').strip()
        if next_url.startswith('/'):
            return redirect(next_url)
        return redirect('web_ui:geofences')

    waypoints = list(
        Waypoint.objects
        .filter(user=request.user, is_active=True)
        .order_by('label')
    )
    devices = list(Device.objects.filter(owner=request.user).order_by('name'))
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    actions = list(
        TransitionAction.objects
        .filter(user=request.user)
        .select_related('waypoint')
        .order_by('waypoint__label', 'event')
    )
    return render(request, 'web_ui/geofences.html', {
        'waypoints': waypoints,
        'devices': devices,
        'user_profile': user_profile,
        'actions': actions,
    })


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
    info = get_server_info(request)

    behind_proxy = bool(os.environ.get('HTTPS_PORT'))

    mqtt_configured_port = get_mqtt_port()
    mqtt_actual_port = get_actual_mqtt_port()
    mqtt_port = mqtt_actual_port if mqtt_actual_port is not None else mqtt_configured_port
    mqtt_enabled = mqtt_configured_port >= 0 and not behind_proxy

    mqtt_tls_port = get_mqtt_tls_port()
    active_sc = ServerCertificate.objects.filter(is_active=True).select_related(
        'issuing_ca',
    ).first()
    mqtt_tls_enabled = mqtt_tls_port >= 0 and active_sc is not None

    context: dict[str, object] = {
        'version': get_version(),
        'server_info': info,
        'hostname': info.hostname,
        'server_port': info.port,
        'server_url': info.base_url,
        'scheme': info.scheme,
        'accessible_hosts': info.accessible_hosts,
        'behind_proxy': behind_proxy,
        'mqtt_port': mqtt_port,
        'mqtt_enabled': mqtt_enabled,
        'mqtt_tls_port': mqtt_tls_port,
        'mqtt_tls_enabled': mqtt_tls_enabled,
        'active_sc': active_sc,
        'public_domain': settings.PUBLIC_DOMAIN,
    }
    return render(request, 'web_ui/about.html', context)


def _is_staff(user: User) -> bool:  # type: ignore[override]
    """Check if user is staff (for use with user_passes_test decorator)."""
    return bool(user.is_staff)


@login_required
@user_passes_test(_is_staff, login_url='/')
def admin_panel(request: HttpRequest) -> HttpResponse:
    """Admin panel for user management."""
    context: dict[str, object] = {}

    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'create_user':
            username = str(request.POST.get('username', '')).strip()
            email = str(request.POST.get('email', '')).strip()
            first_name = str(request.POST.get('first_name', '')).strip()
            last_name = str(request.POST.get('last_name', '')).strip()
            password = str(request.POST.get('password', ''))
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
                    logger.info("[http] User '%s' created '%s' (role=%s) via admin panel",
                                request.user.username, username, role)
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

            request_host = request.get_host().split(":")[0]
            if request_host and request_host not in sc_san_list:
                sc_san_list.append(request_host)
                logger.info(
                    "Auto-included request hostname '%s' in server certificate SANs",
                    request_host,
                )

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
                        logger.info(
                            "Client certificate issued for user '%s' (serial %s, valid %d days) by admin '%s'",
                            target_user.username,
                            hex(serial),
                            validity_days,
                            request.user.username,
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

        if form_type == 'save_smtp':
            host = str(request.POST.get('smtp_host', '')).strip()
            port_raw = str(request.POST.get('smtp_port', '587')).strip()
            username = str(request.POST.get('smtp_username', '')).strip()
            password_raw = request.POST.get('smtp_password', '')
            from_address = str(request.POST.get('smtp_from_address', '')).strip()

            if not host:
                context['smtp_error'] = 'Host is required.'
            elif not from_address:
                context['smtp_error'] = 'From address is required.'
            else:
                try:
                    port = int(port_raw)
                    use_ssl = port == 465
                    use_tls = port in (587, 2525)
                    config = SmtpConfig.get() or SmtpConfig()
                    config.host = host
                    config.port = port
                    config.username = username
                    config.use_tls = use_tls
                    config.use_ssl = use_ssl
                    config.from_address = from_address
                    if password_raw:
                        config.encrypted_password = pki_encrypt_private_key(password_raw.encode())
                    config.save()
                    logger.info("[http] Admin '%s' updated SMTP configuration", request.user.username)
                    context['smtp_success'] = 'SMTP configuration saved.'
                except ValueError:
                    context['smtp_error'] = 'Port must be a number.'
                except Exception as e:
                    context['smtp_error'] = str(e)

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
    smtp_has_message = any(context.get(k) for k in ('smtp_success', 'smtp_error'))
    if smtp_has_message:
        context['active_tab'] = 'email'
    elif pki_has_message:
        context['active_tab'] = 'pki'
    else:
        context['active_tab'] = 'users'

    context['smtp_config'] = SmtpConfig.get()

    admin_info = get_server_info(request)
    san_candidates: list[str] = list(admin_info.lan_ips)
    san_candidates.append(admin_info.hostname)
    for host in admin_info.accessible_hosts:
        if host not in san_candidates:
            san_candidates.append(host)
    context['default_san_list'] = san_candidates
    context['default_sans'] = ', '.join(san_candidates)
    context['hostname'] = admin_info.hostname

    return render(request, 'web_ui/admin_panel.html', context)


@login_required
def action_test(request: HttpRequest) -> JsonResponse:
    """Send a test email for a specific TransitionAction. Returns JSON."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
    action = get_object_or_404(
        TransitionAction, pk=request.POST.get('action_id'), user=request.user
    )
    config = SmtpConfig.get()
    if config is None:
        return JsonResponse({'ok': False, 'error': 'SMTP is not configured yet.'})
    wp_label = action.waypoint.label if action.waypoint else 'any geofence'
    logger.info(
        "[http] User '%s' testing action %s (→ %s)",
        request.user.username, action.pk, action.email_address,
    )
    try:
        from django.core.mail import EmailMessage as DjangoEmailMessage
        backend = get_smtp_backend(config)
        DjangoEmailMessage(
            subject=f"[my-tracks] Test — automation rule for {wp_label}",
            body=(
                f"This is a test of your automation rule:\n\n"
                f"  Geofence: {wp_label}\n"
                f"  Event:    {action.get_event_display()}\n"
                f"  Recipient: {action.email_address}\n\n"
                f"If you receive this, the rule is correctly configured."
            ),
            from_email=config.from_address,
            to=[action.email_address],
            connection=backend,
        ).send()
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': smtp_friendly_error(e)})


@login_required
@user_passes_test(_is_staff, login_url='/')
def smtp_test(request: HttpRequest) -> JsonResponse:
    """Send a test email using the stored SMTP config. Returns JSON."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
    to = str(request.POST.get('to', '')).strip()
    if not to:
        return JsonResponse({'ok': False, 'error': 'Recipient address is required.'})
    config = SmtpConfig.get()
    if config is None:
        return JsonResponse({'ok': False, 'error': 'SMTP is not configured yet.'})
    active_sc = ServerCertificate.objects.filter(is_active=True).first()
    server_names = (
        get_certificate_sans(active_sc.certificate_pem.encode())
        if active_sc else None
    )
    logger.info("[http] Admin '%s' sending test email to %s", request.user.username, to)
    try:
        send_test_email(to, config, server_names=server_names)
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': smtp_friendly_error(e)})
