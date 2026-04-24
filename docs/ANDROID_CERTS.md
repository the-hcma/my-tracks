# Android: Install / Remove MQTT TLS Certificates

My Tracks uses its own PKI for **MQTT over TLS (MQTTS)**. On Android, you typically install:

- A **CA certificate** (the My Tracks CA) so the client can trust the broker.
- A **client certificate** (your personal identity) to authenticate to the broker.

> Android’s Settings UI changes between versions and OEM skins. The menu labels below are **representative**; if you can’t find an item, use Settings search for: “certificates”, “credentials”, “trusted credentials”, or “install certificate”.

## Files you’ll download from My Tracks

- **CA certificate**: `*.pem` (CA public cert)
- **Client certificate bundle**: `*.p12` (PKCS#12), password-protected

## Install

### Install the CA certificate (trust the broker)

1. Download the CA certificate (`.pem`) to your phone.
2. Open **Settings**.
3. Go to (one of the common paths):
   - **Security & privacy** → **More security settings** → **Encryption & credentials**
   - or **Security** → **Encryption & credentials**
4. Tap **Install a certificate** (or **Install from storage**).
5. Choose **CA certificate**.
6. Select the downloaded `.pem` file.
7. Confirm any prompts (Android may warn that installing a CA can let that CA inspect TLS traffic — in this case it’s your own self-hosted CA for your broker).

After this, Android should show the CA under **Trusted credentials** (often under the **User** tab).

### Install the client certificate (authenticate to the broker)

1. Download the client certificate bundle (`.p12`) to your phone.
2. Open **Settings**.
3. Navigate to **Encryption & credentials** (see CA steps above).
4. Tap **Install a certificate** (or **Install from storage**).
5. Choose **VPN & app user certificate** (sometimes “User certificate”).
6. Select the downloaded `.p12` file.
7. When prompted, enter the **password** that was used to encrypt the `.p12` bundle.

After this, Android should show the client cert under **User credentials**.

### Select the client certificate in OwnTracks

Installing the certificate in Android only makes it available to apps. You must also tell OwnTracks to use it:

1. Open **OwnTracks**.
2. Go to **Preferences** (or **Settings**).
3. Tap **Connection**.
4. Tap **Client Certificate**.
5. Pick the client certificate you installed (the `.p12` / “VPN & app user” cert).

## Remove / Uninstall

### Remove the CA certificate

1. Open **Settings**.
2. Go to **Security & privacy** → **More security settings** → **Encryption & credentials**.
3. Tap **Trusted credentials** → go to the **User** tab.
4. Tap the CA certificate and choose **Remove** or **Disable**.

### Remove the client certificate

1. Open **Settings**.
2. Go to **Security & privacy** → **More security settings** → **Encryption & credentials**.
3. Tap **User credentials**.
4. Select the certificate and choose **Remove**.
   - Some Android builds require a long-press to reveal the remove option.

## Notes / Troubleshooting

- **If MQTT TLS connects but then disconnects immediately**: double-check the broker hostname you’re using is present in the server certificate SANs, and that you installed the correct CA.
- **If the certificate can’t be selected in an app**: some apps only look for “VPN & app user” certs (client certs) and won’t use CA certs unless explicitly configured.
- **OwnTracks MQTT version**: My Tracks requires MQTT v3.1.1 (protocol level 4). If you see “MQTT v3.1 connection detected” in logs, import a config file with:

```json
{"_type": "configuration", "mqttProtocolLevel": 4}
```

