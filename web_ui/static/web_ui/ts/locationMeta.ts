/**
 * Format OwnTracks vertical-accuracy and network metadata for activity log rows.
 */

export interface LocationMetaFields {
    accuracy?: number;
    altitude?: number;
    velocity?: number;
    battery_level?: number;
    connection_type?: string;
    vertical_accuracy?: number;
    fix_source?: string;
    wifi_ssid?: string;
}

export function formatConnectionDisplay(
    connectionType?: string,
    wifiSsid?: string,
): string {
    if (!connectionType) {
        return 'N/A';
    }
    if (connectionType === 'w') {
        return wifiSsid ? `WiFi (${wifiSsid})` : 'WiFi';
    }
    if (connectionType === 'm') {
        return 'Mobile';
    }
    if (connectionType === 'o') {
        return 'Offline';
    }
    return connectionType;
}

export function formatActivityLogMeta(loc: LocationMetaFields): string {
    const accPart =
        loc.accuracy !== undefined && loc.accuracy !== null
            ? `acc:${loc.accuracy}m`
            : 'acc:N/A';
    const vacPart =
        loc.vertical_accuracy !== undefined && loc.vertical_accuracy !== null
            ? ` vac:${loc.vertical_accuracy}m`
            : '';
    const alt = loc.altitude ?? 0;
    const vel = loc.velocity ?? 0;
    const batt = loc.battery_level ?? 'N/A';
    const conn = formatConnectionDisplay(loc.connection_type, loc.wifi_ssid);
    const srcPart = loc.fix_source ? ` src:${loc.fix_source}` : '';
    return `${accPart}${vacPart} alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}${srcPart}`;
}
