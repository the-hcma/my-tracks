/**
 * Tests for friend request banner helpers.
 */
import { describe, it, expect } from 'vitest';
import { formatFriendRequestBannerText } from './friend-request-banner';
import type { FriendRequestRow } from './friend-request-banner';

describe('formatFriendRequestBannerText', () => {
    it('returns empty string when there are no requests', () => {
        expect(formatFriendRequestBannerText([])).toBe('');
    });

    it('uses singular wording for one request', () => {
        const rows: FriendRequestRow[] = [
            { id: 1, from_user: 'kristen', to_user: 'alice', status: 'pending', created_at: '' },
        ];
        expect(formatFriendRequestBannerText(rows)).toBe('kristen sent you a friend request.');
    });

    it('summarizes multiple requests', () => {
        const rows: FriendRequestRow[] = [
            { id: 1, from_user: 'kristen', to_user: 'alice', status: 'pending', created_at: '' },
            { id: 2, from_user: 'bob', to_user: 'alice', status: 'pending', created_at: '' },
            { id: 3, from_user: 'charlie', to_user: 'alice', status: 'pending', created_at: '' },
        ];
        expect(formatFriendRequestBannerText(rows)).toBe(
            'kristen, bob, and 1 more sent you friend requests.',
        );
    });
});
