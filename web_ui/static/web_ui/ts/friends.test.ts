/**
 * Tests for Friends tab helpers.
 */
import { describe, it, expect } from 'vitest';
import { filterOwnedDevices, formatFriendLabel } from './friends';
import type { DeviceRow, FriendRow } from './friends';

describe('formatFriendLabel', () => {
    it('uses first and last name with username when present', () => {
        const friend: FriendRow = {
            user_id: 1,
            username: 'bob',
            first_name: 'Bob',
            last_name: 'Smith',
        };
        expect(formatFriendLabel(friend)).toBe('Bob Smith (bob)');
    });

    it('falls back to username when name fields are empty', () => {
        const friend: FriendRow = {
            user_id: 2,
            username: 'alice',
            first_name: '',
            last_name: '',
        };
        expect(formatFriendLabel(friend)).toBe('alice');
    });
});

describe('filterOwnedDevices', () => {
    const devices: DeviceRow[] = [
        { device_id: 'mine', name: 'Mine', owner_username: 'alice' },
        { device_id: 'theirs', name: 'Theirs', owner_username: 'bob' },
        { device_id: 'orphan', name: 'Orphan', owner_username: '' },
    ];

    it('keeps only devices owned by the current user', () => {
        expect(filterOwnedDevices(devices, 'alice')).toEqual([
            { device_id: 'mine', name: 'Mine', owner_username: 'alice' },
        ]);
    });

    it('returns empty list when user owns nothing', () => {
        expect(filterOwnedDevices(devices, 'charlie')).toEqual([]);
    });
});
