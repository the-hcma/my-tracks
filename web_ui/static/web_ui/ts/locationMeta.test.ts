/**
 * Tests for location metadata formatting in activity logs.
 */
import { describe, expect, it } from 'vitest';
import { formatActivityLogMeta, formatConnectionDisplay } from './locationMeta';

describe('formatConnectionDisplay', () => {
    it('shows WiFi with SSID when available', () => {
        expect(formatConnectionDisplay('w', 'familia')).toBe('WiFi (familia)');
    });

    it('shows plain WiFi without SSID', () => {
        expect(formatConnectionDisplay('w')).toBe('WiFi');
    });

    it('maps mobile and offline codes', () => {
        expect(formatConnectionDisplay('m')).toBe('Mobile');
        expect(formatConnectionDisplay('o')).toBe('Offline');
    });

    it('returns N/A when connection is missing', () => {
        expect(formatConnectionDisplay()).toBe('N/A');
    });
});

describe('formatActivityLogMeta', () => {
    it('includes vertical accuracy and network metadata', () => {
        const meta = formatActivityLogMeta({
            accuracy: 10,
            altitude: 50,
            velocity: 5,
            battery_level: 85,
            vertical_accuracy: 100,
            fix_source: 'network',
            connection_type: 'w',
            wifi_ssid: 'familia',
        });
        expect(meta).toBe(
            'acc:10m vac:100m alt:50m vel:5km/h batt:85% WiFi (familia) src:network',
        );
    });

    it('omits optional vac and source when absent', () => {
        const meta = formatActivityLogMeta({
            connection_type: 'm',
        });
        expect(meta).toBe('acc:N/A alt:0m vel:0km/h batt:N/A% Mobile');
    });
});
