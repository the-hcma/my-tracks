# Troubleshooting

Common issues and their solutions.

---

## OwnTracks Android: commands delivered but phone doesn't respond

**Symptom**: The server log shows a command was sent (e.g. `reportLocation command sent to hcma/pixel7pro`), and the OwnTracks debug log confirms it was received and parsed, but no location or waypoints response arrives at the server.

**Cause**: OwnTracks uses an internal `BackgroundService` that handles location requests on behalf of `MessageProcessor`. The binding between them is established once on first start and never re-established if the service is killed. If Android kills and restarts the background service (due to memory pressure, battery optimisation, or any other reason), the binding becomes `null` and remote commands silently do nothing — no error is logged by the app.

**Fix**: Force-stop OwnTracks and reopen it.

1. Long-press the OwnTracks icon → **App info** (or go to **Settings → Apps → OwnTracks**).
2. Tap **Force Stop**.
3. Reopen OwnTracks.
4. Wait a few seconds for the MQTT connection to re-establish (the server log will show the device reconnect).
5. Retry the command.

After a proper restart the `BackgroundService` binding is re-established and `reportLocation`, `fetchWaypoints`, and other commands will respond normally.

> **Note**: Clearing the in-memory debug log from within the OwnTracks app does **not** restart the service. Only a force-stop does.

---

## OwnTracks Android: `fetchWaypoints` returns count=0

**Symptom**: The server log shows `Waypoints upserted: device=…, processed=0`.

**Cause**: The phone responded correctly — it has no waypoints (regions) configured yet. This is expected on a fresh install.

**Fix**: No fix needed. Add waypoints (geofence regions) in OwnTracks via **Regions** in the app menu, and the next `fetchWaypoints` command will return them.

---

## OwnTracks Android: MQTT connects then immediately disconnects (wrong protocol version)

**Symptom**: OwnTracks connects but immediately drops, or the server log shows:

```
WARNING  … MQTT v3.1 connection detected from client … Use MQTT v3.1.1
```

**Cause**: OwnTracks Android defaults to MQTT v3.1 (protocol level 3). My Tracks uses amqtt, which only supports MQTT v3.1.1 (protocol level 4). The broker rejects v3.1 connections.

**Fix**: Import the configuration file into OwnTracks. It is checked in at [`etc/owntracks.json`](../etc/owntracks.json).

Then import it into OwnTracks:

1. Copy the file to your phone (AirDrop, email, USB, etc.).
2. Open **OwnTracks**.
3. Tap the menu (≡) → **Preferences** → **Import/Export** (or tap the share/import icon in Settings).
4. Select the `owntracks.json` file.
5. OwnTracks will apply the setting and reconnect.

After importing, the protocol version in **Preferences → Connection → Advanced** should show **MQTT 3.1.1**.

---

## OwnTracks Android: certificate / TLS connection issues

See [ANDROID_CERTS.md](ANDROID_CERTS.md) for full instructions on installing the CA certificate and client certificate.

---

## Server: MQTT PUBACK timeout warning

**Symptom**: Log line like:

```
WARNING  amqtt … Client … timeout after 5s
```

**Cause**: The amqtt broker waits up to 5 seconds for a QoS 1 PUBACK from the phone after delivering a message. If the phone takes longer than 5 seconds to ACK (e.g. it is waking up from sleep), amqtt logs this warning. The message has already been delivered; this is noise.

**Fix**: No action required. The phone will ACK eventually and delivery succeeds. The warning can be safely ignored.
