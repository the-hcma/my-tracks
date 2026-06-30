/**
 * Report vs fix time for live activity (OwnTracks tst vs created_at / received_at).
 * See https://github.com/the-hcma/my-tracks/issues/1197
 */

export interface LocationReportFields {
    reported_at_unix?: number;
    timestamp_unix?: number;
    fix_age_seconds?: number;
    trigger?: string;
}

/** Primary ordering/display time: when the device report was built or ingested. */
export function locationReportedAtUnix(loc: LocationReportFields): number {
    return loc.reported_at_unix ?? loc.timestamp_unix ?? 0;
}

/** Show fix-age note when report time is meaningfully later than GPS fix (tst). */
export const FIX_AGE_LABEL_THRESHOLD_SECONDS = 60;

export function formatTriggerLabel(trigger?: string): string | null {
    if (!trigger) {
        return null;
    }
    switch (trigger) {
        case 'p':
            return 'ping';
        case 'r':
            return 'reportLocation';
        case 'u':
            return 'manual';
        case 't':
            return 'move timer';
        case 'c':
        case 'C':
            return 'region';
        case 'b':
            return 'beacon';
        case 'v':
            return 'frequent locations';
        default:
            return trigger;
    }
}

export function formatDurationShort(totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    const parts: string[] = [];
    if (hours > 0) {
        parts.push(`${hours}h`);
    }
    if (minutes > 0) {
        parts.push(`${minutes}m`);
    }
    if (hours === 0 && (minutes === 0 || secs > 0)) {
        parts.push(`${secs}s`);
    }
    return parts.join(' ') || '0s';
}

/**
 * Human-readable note when fix (tst) predates the report.
 * @param fixTimeLabel - pre-formatted fix time string
 */
export function formatFixAgeNote(
    fixAgeSeconds: number,
    fixTimeLabel: string,
): string | null {
    if (fixAgeSeconds < FIX_AGE_LABEL_THRESHOLD_SECONDS) {
        return null;
    }
    return `Position from ${fixTimeLabel} (${formatDurationShort(fixAgeSeconds)} before this report)`;
}

/** Always show when the GPS fix was observed (live activity log second line). */
export function formatFixObservedLogLine(fixTimeLabel: string, fixAgeSeconds: number): string {
    const staleNote = formatFixAgeNote(fixAgeSeconds, fixTimeLabel);
    if (staleNote !== null) {
        return staleNote;
    }
    return `Fix observed: ${fixTimeLabel}`;
}

export function compareLocationsByReportTimeDesc(
    a: LocationReportFields,
    b: LocationReportFields,
): number {
    return locationReportedAtUnix(b) - locationReportedAtUnix(a);
}
