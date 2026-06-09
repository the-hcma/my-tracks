/**
 * Site-wide banner for incoming friend requests (home, profile, etc.).
 */

export interface FriendRequestRow {
    id: number;
    from_user: string;
    to_user: string;
    status: string;
    created_at: string;
}

export interface PendingFriendRequests {
    received: FriendRequestRow[];
    sent: FriendRequestRow[];
}

export interface FriendRequestBannerOptions {
    root: HTMLElement;
    profileUrl: string;
}

export function formatFriendRequestBannerText(received: FriendRequestRow[]): string {
    if (received.length === 0) {
        return '';
    }
    if (received.length === 1) {
        return `${received[0].from_user} sent you a friend request.`;
    }
    const names = received.slice(0, 2).map((row) => row.from_user);
    if (received.length === 2) {
        return `${names[0]} and ${names[1]} sent you friend requests.`;
    }
    return `${names[0]}, ${names[1]}, and ${received.length - 2} more sent you friend requests.`;
}

export async function fetchPendingFriendRequests(): Promise<PendingFriendRequests> {
    const response = await fetch('/api/friends/requests/', { credentials: 'same-origin' });
    if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
    }
    return (await response.json()) as PendingFriendRequests;
}

export function initFriendRequestBanner(options: FriendRequestBannerOptions): {
    refresh: () => Promise<void>;
} {
    const { root, profileUrl } = options;

    function render(received: FriendRequestRow[]): void {
        root.replaceChildren();
        if (received.length === 0) {
            root.hidden = true;
            return;
        }

        const banner = document.createElement('div');
        banner.className = 'friend-request-banner';
        banner.setAttribute('role', 'status');

        const text = document.createElement('span');
        text.className = 'friend-request-banner-text';
        text.textContent = formatFriendRequestBannerText(received);

        const link = document.createElement('a');
        link.className = 'friend-request-banner-link';
        link.href = profileUrl;
        link.textContent = 'View requests';

        banner.append(text, link);
        root.appendChild(banner);
        root.hidden = false;
    }

    async function refresh(): Promise<void> {
        try {
            const pending = await fetchPendingFriendRequests();
            render(pending.received);
        } catch {
            root.hidden = true;
        }
    }

    void refresh();
    window._friendRequestBannerRefresh = refresh;
    return { refresh };
}

function bootstrapFriendRequestBanner(): void {
    const root = document.getElementById('friend-request-banner-root');
    if (!root) {
        return;
    }
    initFriendRequestBanner({
        root,
        profileUrl: root.dataset.profileUrl || '/profile/#friends',
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapFriendRequestBanner);
} else {
    bootstrapFriendRequestBanner();
}

declare global {
    interface Window {
        _friendRequestBannerRefresh?: () => Promise<void>;
    }
}
