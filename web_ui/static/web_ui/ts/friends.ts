/**
 * Profile page — Friends tab: requests, friend list, per-device sharing.
 */

import { extractResultsList } from './utils';
import type { MessageType, ShowMessageOptions } from './messages';

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

export interface FriendRow {
    user_id: number;
    username: string;
    first_name: string;
    last_name: string;
}

export interface DeviceRow {
    device_id: string;
    name: string;
    owner_username: string;
}

export interface DeviceShareRow {
    id: number;
    device_id: string;
    device_name: string;
    shared_with_id: number;
    created_at: string;
}

export interface UserSearchRow {
    username: string;
    first_name: string;
    last_name: string;
}

export type ShowMessageFn = (
    container: HTMLElement,
    type: MessageType,
    text: string,
    options?: ShowMessageOptions,
) => void;

export interface FriendsTabOptions {
    root: HTMLElement;
    csrfToken: string;
    currentUsername: string;
    showMessage: ShowMessageFn;
}

/** Human-readable label for a friend row. */
export function formatFriendLabel(friend: FriendRow): string {
    const parts = [friend.first_name, friend.last_name].filter(Boolean);
    if (parts.length > 0) {
        return `${parts.join(' ')} (${friend.username})`;
    }
    return friend.username;
}

/** Devices the current user can share with friends. */
export function filterOwnedDevices(devices: DeviceRow[], ownerUsername: string): DeviceRow[] {
    return devices.filter((d) => d.owner_username === ownerUsername);
}

/** Label for a username autocomplete suggestion. */
export function formatUserSearchLabel(user: UserSearchRow): string {
    const parts = [user.first_name, user.last_name].filter(Boolean);
    if (parts.length > 0) {
        return `${user.username} — ${parts.join(' ')}`;
    }
    return user.username;
}

/** Client-side filter when reusing a cached suggestion list. */
export function filterUserSearchResults(users: UserSearchRow[], query: string): UserSearchRow[] {
    const q = query.trim().toLowerCase();
    if (!q) {
        return users;
    }
    return users.filter((user) => {
        const username = user.username.toLowerCase();
        const fullName = [user.first_name, user.last_name].join(' ').toLowerCase();
        return username.startsWith(q) || fullName.includes(q);
    });
}

function apiHeaders(csrfToken: string, json = false): HeadersInit {
    const headers: Record<string, string> = {
        'X-CSRFToken': csrfToken,
    };
    if (json) {
        headers['Content-Type'] = 'application/json';
    }
    return headers;
}

async function readError(response: Response): Promise<string> {
    try {
        const data = (await response.json()) as { error?: string };
        if (data.error) {
            return data.error;
        }
    } catch {
        // ignore parse errors
    }
    return `Request failed (${response.status})`;
}

export async function fetchFriendRequests(csrfToken: string): Promise<PendingFriendRequests> {
    const response = await fetch('/api/friends/requests/', {
        headers: apiHeaders(csrfToken),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        throw new Error(await readError(response));
    }
    return (await response.json()) as PendingFriendRequests;
}

export async function fetchFriends(csrfToken: string): Promise<FriendRow[]> {
    const response = await fetch('/api/friends/', {
        headers: apiHeaders(csrfToken),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        throw new Error(await readError(response));
    }
    return (await response.json()) as FriendRow[];
}

export async function fetchMyDevices(csrfToken: string): Promise<DeviceRow[]> {
    const response = await fetch('/api/devices/', {
        headers: apiHeaders(csrfToken),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        throw new Error(await readError(response));
    }
    const data = await response.json();
    return extractResultsList<DeviceRow>(data);
}

export async function fetchUserSearch(csrfToken: string, query: string): Promise<UserSearchRow[]> {
    const q = query.trim();
    if (!q) {
        return [];
    }
    const response = await fetch(`/api/friends/user-search/?q=${encodeURIComponent(q)}`, {
        headers: apiHeaders(csrfToken),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        throw new Error(await readError(response));
    }
    return (await response.json()) as UserSearchRow[];
}

export async function fetchSharesForFriend(
    csrfToken: string,
    friendUserId: number,
): Promise<DeviceShareRow[]> {
    const response = await fetch(`/api/friends/${friendUserId}/shares/`, {
        headers: apiHeaders(csrfToken),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        throw new Error(await readError(response));
    }
    return (await response.json()) as DeviceShareRow[];
}

export function initFriendsTab(options: FriendsTabOptions): { refresh: () => Promise<void> } {
    const { root, csrfToken, currentUsername, showMessage } = options;

    const pendingReceived = root.querySelector<HTMLElement>('#friends-pending-received');
    const pendingSent = root.querySelector<HTMLElement>('#friends-pending-sent');
    const friendsList = root.querySelector<HTMLElement>('#friends-list');
    const addForm = root.querySelector<HTMLFormElement>('#friends-add-form');
    const usernameInput = root.querySelector<HTMLInputElement>('#friends-add-username');
    const suggestionsBox = root.querySelector<HTMLElement>('#friends-username-suggestions');
    const autoAcceptInput = root.querySelector<HTMLInputElement>('#friends-auto-accept-reciprocal');
    const statusBox = root.querySelector<HTMLElement>('#friends-status');

    if (
        !pendingReceived ||
        !pendingSent ||
        !friendsList ||
        !addForm ||
        !usernameInput ||
        !suggestionsBox ||
        !autoAcceptInput ||
        !statusBox
    ) {
        return { refresh: async () => {} };
    }

    const pendingReceivedEl = pendingReceived;
    const pendingSentEl = pendingSent;
    const friendsListEl = friendsList;
    const addFormEl = addForm;
    const usernameInputEl = usernameInput;
    const suggestionsBoxEl = suggestionsBox;
    const autoAcceptInputEl = autoAcceptInput;
    const statusBoxEl = statusBox;

    let suggestionTimer: ReturnType<typeof setTimeout> | null = null;
    let activeSuggestionIndex = -1;
    let latestSuggestions: UserSearchRow[] = [];

    function flash(type: MessageType, text: string): void {
        showMessage(statusBoxEl, type, text);
    }

    function hideSuggestions(): void {
        suggestionsBoxEl.replaceChildren();
        suggestionsBoxEl.hidden = true;
        usernameInputEl.setAttribute('aria-expanded', 'false');
        activeSuggestionIndex = -1;
        latestSuggestions = [];
    }

    function selectSuggestion(user: UserSearchRow): void {
        usernameInputEl.value = user.username;
        hideSuggestions();
        usernameInputEl.focus();
    }

    function renderSuggestions(users: UserSearchRow[]): void {
        latestSuggestions = users;
        suggestionsBoxEl.replaceChildren();
        if (users.length === 0) {
            hideSuggestions();
            return;
        }

        for (const [index, user] of users.entries()) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'friends-suggestion-btn';
            button.dataset.index = String(index);

            const username = document.createElement('span');
            username.textContent = user.username;

            const parts = [user.first_name, user.last_name].filter(Boolean);
            button.append(username);
            if (parts.length > 0) {
                const name = document.createElement('span');
                name.className = 'friends-suggestion-name';
                name.textContent = ` — ${parts.join(' ')}`;
                button.append(name);
            }

            button.addEventListener('mousedown', (event) => {
                event.preventDefault();
                selectSuggestion(user);
            });
            suggestionsBoxEl.appendChild(button);
        }

        suggestionsBoxEl.hidden = false;
        usernameInputEl.setAttribute('aria-expanded', 'true');
        activeSuggestionIndex = -1;
    }

    function highlightSuggestion(index: number): void {
        const buttons = suggestionsBoxEl.querySelectorAll<HTMLButtonElement>('.friends-suggestion-btn');
        buttons.forEach((button, buttonIndex) => {
            button.style.background =
                buttonIndex === index ? 'rgba(78, 154, 241, 0.12)' : '';
        });
        activeSuggestionIndex = index;
    }

    async function updateSuggestions(): Promise<void> {
        const query = usernameInputEl.value.trim();
        if (!query) {
            hideSuggestions();
            return;
        }
        try {
            const users = await fetchUserSearch(csrfToken, query);
            renderSuggestions(filterUserSearchResults(users, query));
        } catch {
            hideSuggestions();
        }
    }

    function scheduleSuggestionUpdate(): void {
        if (suggestionTimer) {
            clearTimeout(suggestionTimer);
        }
        suggestionTimer = setTimeout(() => {
            void updateSuggestions();
        }, 200);
    }

    usernameInputEl.addEventListener('input', () => {
        scheduleSuggestionUpdate();
    });

    usernameInputEl.addEventListener('focus', () => {
        if (usernameInputEl.value.trim()) {
            scheduleSuggestionUpdate();
        }
    });

    usernameInputEl.addEventListener('blur', () => {
        setTimeout(() => {
            hideSuggestions();
        }, 150);
    });

    usernameInputEl.addEventListener('keydown', (event) => {
        if (suggestionsBoxEl.hidden || latestSuggestions.length === 0) {
            return;
        }
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            const next = Math.min(activeSuggestionIndex + 1, latestSuggestions.length - 1);
            highlightSuggestion(next);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            const next = Math.max(activeSuggestionIndex - 1, 0);
            highlightSuggestion(next);
        } else if (event.key === 'Enter' && activeSuggestionIndex >= 0) {
            event.preventDefault();
            const selected = latestSuggestions[activeSuggestionIndex];
            if (selected) {
                selectSuggestion(selected);
            }
        } else if (event.key === 'Escape') {
            hideSuggestions();
        }
    });

    async function sendRequest(username: string, autoAcceptReciprocal: boolean): Promise<string> {
        const response = await fetch('/api/friends/requests/', {
            method: 'POST',
            headers: apiHeaders(csrfToken, true),
            credentials: 'same-origin',
            body: JSON.stringify({
                username,
                auto_accept_reciprocal: autoAcceptReciprocal,
            }),
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
        const data = (await response.json()) as { status?: string };
        return data.status ?? 'pending';
    }

    async function acceptRequest(requestId: number, autoAcceptReciprocal: boolean): Promise<void> {
        const response = await fetch(`/api/friends/requests/${requestId}/accept/`, {
            method: 'POST',
            headers: apiHeaders(csrfToken, true),
            credentials: 'same-origin',
            body: JSON.stringify({ auto_accept_reciprocal: autoAcceptReciprocal }),
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
    }

    async function cancelSentRequest(requestId: number): Promise<void> {
        const response = await fetch(`/api/friends/requests/${requestId}/`, {
            method: 'DELETE',
            headers: apiHeaders(csrfToken),
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
    }

    async function declineRequest(requestId: number): Promise<void> {
        const response = await fetch(`/api/friends/requests/${requestId}/decline/`, {
            method: 'POST',
            headers: apiHeaders(csrfToken),
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
    }

    async function removeFriend(friendUserId: number): Promise<void> {
        const response = await fetch(`/api/friends/${friendUserId}/`, {
            method: 'DELETE',
            headers: apiHeaders(csrfToken),
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
    }

    async function createShare(friendUserId: number, deviceId: string): Promise<void> {
        const response = await fetch(`/api/friends/${friendUserId}/shares/`, {
            method: 'POST',
            headers: apiHeaders(csrfToken, true),
            credentials: 'same-origin',
            body: JSON.stringify({ device_id: deviceId }),
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
    }

    async function deleteShare(friendUserId: number, deviceId: string): Promise<void> {
        const response = await fetch(
            `/api/friends/${friendUserId}/shares/${encodeURIComponent(deviceId)}/`,
            {
                method: 'DELETE',
                headers: apiHeaders(csrfToken),
                credentials: 'same-origin',
            },
        );
        if (!response.ok) {
            throw new Error(await readError(response));
        }
    }

    function renderPendingReceived(requests: FriendRequestRow[]): void {
        pendingReceivedEl.replaceChildren();
        if (requests.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'cert-none';
            empty.textContent = 'No incoming friend requests.';
            pendingReceivedEl.appendChild(empty);
            return;
        }

        const table = document.createElement('table');
        table.className = 'devices-table';
        table.innerHTML =
            '<thead><tr><th>From</th><th>Received</th><th></th></tr></thead>';
        const tbody = document.createElement('tbody');

        for (const req of requests) {
            const tr = document.createElement('tr');

            const fromTd = document.createElement('td');
            fromTd.textContent = req.from_user;

            const whenTd = document.createElement('td');
            whenTd.className = 'muted';
            const when = new Date(req.created_at);
            whenTd.textContent = Number.isNaN(when.getTime())
                ? req.created_at
                : when.toLocaleString();

            const actionsTd = document.createElement('td');
            actionsTd.style.textAlign = 'right';
            actionsTd.style.whiteSpace = 'nowrap';

            const reciprocalLabel = document.createElement('label');
            reciprocalLabel.className = 'friend-share-item friends-accept-reciprocal';
            reciprocalLabel.style.display = 'inline-flex';
            reciprocalLabel.style.marginRight = '0.5rem';
            reciprocalLabel.style.fontSize = '0.8rem';
            const reciprocalCheckbox = document.createElement('input');
            reciprocalCheckbox.type = 'checkbox';
            reciprocalLabel.append(
                reciprocalCheckbox,
                document.createTextNode(' Send request back (auto-accept)'),
            );

            const acceptBtn = document.createElement('button');
            acceptBtn.type = 'button';
            acceptBtn.className = 'cert-btn';
            acceptBtn.style.marginRight = '0.35rem';
            acceptBtn.textContent = 'Accept';
            acceptBtn.addEventListener('click', () => {
                void (async () => {
                    acceptBtn.disabled = true;
                    declineBtn.disabled = true;
                    reciprocalCheckbox.disabled = true;
                    try {
                        await acceptRequest(req.id, reciprocalCheckbox.checked);
                        flash('success', `You are now friends with ${req.from_user}.`);
                        await refresh();
                    } catch (err) {
                        flash('error', err instanceof Error ? err.message : 'Accept failed.');
                        acceptBtn.disabled = false;
                        declineBtn.disabled = false;
                        reciprocalCheckbox.disabled = false;
                    }
                })();
            });

            const declineBtn = document.createElement('button');
            declineBtn.type = 'button';
            declineBtn.className = 'cert-btn';
            declineBtn.style.background = 'rgba(231,76,60,.15)';
            declineBtn.style.color = 'var(--error)';
            declineBtn.style.border = '1px solid rgba(231,76,60,.35)';
            declineBtn.textContent = 'Decline';
            declineBtn.addEventListener('click', () => {
                void (async () => {
                    declineBtn.disabled = true;
                    acceptBtn.disabled = true;
                    reciprocalCheckbox.disabled = true;
                    try {
                        await declineRequest(req.id);
                        flash('success', `Declined request from ${req.from_user}.`);
                        await refresh();
                    } catch (err) {
                        flash('error', err instanceof Error ? err.message : 'Decline failed.');
                        declineBtn.disabled = false;
                        acceptBtn.disabled = false;
                        reciprocalCheckbox.disabled = false;
                    }
                })();
            });

            actionsTd.append(reciprocalLabel, acceptBtn, declineBtn);
            tr.append(fromTd, whenTd, actionsTd);
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        pendingReceivedEl.appendChild(table);
    }

    function renderPendingSent(requests: FriendRequestRow[]): void {
        pendingSentEl.replaceChildren();
        if (requests.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'cert-none';
            empty.textContent = 'No outgoing friend requests.';
            pendingSentEl.appendChild(empty);
            return;
        }

        const table = document.createElement('table');
        table.className = 'devices-table';
        table.innerHTML = '<thead><tr><th>To</th><th>Sent</th><th></th></tr></thead>';
        const tbody = document.createElement('tbody');

        for (const req of requests) {
            const tr = document.createElement('tr');

            const toTd = document.createElement('td');
            toTd.textContent = req.to_user;

            const whenTd = document.createElement('td');
            whenTd.className = 'muted';
            const when = new Date(req.created_at);
            whenTd.textContent = Number.isNaN(when.getTime())
                ? req.created_at
                : when.toLocaleString();

            const actionsTd = document.createElement('td');
            actionsTd.style.textAlign = 'right';
            actionsTd.style.whiteSpace = 'nowrap';

            const cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'cert-btn';
            cancelBtn.style.background = 'rgba(231,76,60,.15)';
            cancelBtn.style.color = 'var(--error)';
            cancelBtn.style.border = '1px solid rgba(231,76,60,.35)';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.addEventListener('click', () => {
                void (async () => {
                    cancelBtn.disabled = true;
                    try {
                        await cancelSentRequest(req.id);
                        flash('success', `Canceled request to ${req.to_user}.`);
                        await refresh();
                    } catch (err) {
                        flash('error', err instanceof Error ? err.message : 'Cancel failed.');
                        cancelBtn.disabled = false;
                    }
                })();
            });

            actionsTd.appendChild(cancelBtn);
            tr.append(toTd, whenTd, actionsTd);
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        pendingSentEl.appendChild(table);
    }

    function renderFriends(
        friends: FriendRow[],
        ownedDevices: DeviceRow[],
        sharesByFriendId: Map<number, Set<string>>,
    ): void {
        friendsListEl.replaceChildren();
        if (friends.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'cert-none';
            empty.textContent = 'No friends yet. Send a request above to get started.';
            friendsListEl.appendChild(empty);
            return;
        }

        for (const friend of friends) {
            const card = document.createElement('div');
            card.className = 'friend-card';

            const header = document.createElement('div');
            header.className = 'friend-card-header';

            const title = document.createElement('strong');
            title.textContent = formatFriendLabel(friend);

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'friend-remove-btn';
            removeBtn.textContent = 'Remove friend';
            removeBtn.addEventListener('click', () => {
                if (!window.confirm(`Remove ${friend.username} as a friend? Device shares will be revoked.`)) {
                    return;
                }
                void (async () => {
                    removeBtn.disabled = true;
                    try {
                        await removeFriend(friend.user_id);
                        flash('success', `Removed ${friend.username}.`);
                        await refresh();
                    } catch (err) {
                        flash('error', err instanceof Error ? err.message : 'Remove failed.');
                        removeBtn.disabled = false;
                    }
                })();
            });

            header.append(title, removeBtn);
            card.appendChild(header);

            const shareTitle = document.createElement('div');
            shareTitle.className = 'friend-share-title';
            shareTitle.textContent = 'Share devices';
            card.appendChild(shareTitle);

            if (ownedDevices.length === 0) {
                const none = document.createElement('p');
                none.className = 'cert-none';
                none.style.marginTop = '0.5rem';
                none.textContent = 'No devices on your account to share.';
                card.appendChild(none);
            } else {
                const shareList = document.createElement('div');
                shareList.className = 'friend-share-list';
                const sharedIds = sharesByFriendId.get(friend.user_id) ?? new Set<string>();

                for (const device of ownedDevices) {
                    const label = document.createElement('label');
                    label.className = 'friend-share-item';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.checked = sharedIds.has(device.device_id);
                    checkbox.addEventListener('change', () => {
                        const deviceId = device.device_id;
                        const friendId = friend.user_id;
                        checkbox.disabled = true;
                        void (async () => {
                            try {
                                if (checkbox.checked) {
                                    await createShare(friendId, deviceId);
                                } else {
                                    await deleteShare(friendId, deviceId);
                                }
                            } catch (err) {
                                checkbox.checked = !checkbox.checked;
                                flash(
                                    'error',
                                    err instanceof Error ? err.message : 'Share update failed.',
                                );
                            } finally {
                                checkbox.disabled = false;
                            }
                        })();
                    });

                    const text = document.createElement('span');
                    const displayName = device.name?.trim() || device.device_id;
                    text.textContent =
                        displayName === device.device_id
                            ? device.device_id
                            : `${displayName} (${device.device_id})`;

                    label.append(checkbox, text);
                    shareList.appendChild(label);
                }

                card.appendChild(shareList);
            }

            friendsListEl.appendChild(card);
        }
    }

    async function refresh(): Promise<void> {
        try {
            const [requests, friends, devices] = await Promise.all([
                fetchFriendRequests(csrfToken),
                fetchFriends(csrfToken),
                fetchMyDevices(csrfToken),
            ]);
            const ownedDevices = filterOwnedDevices(devices, currentUsername);

            const shareEntries = await Promise.all(
                friends.map(async (friend) => {
                    const shares = await fetchSharesForFriend(csrfToken, friend.user_id);
                    return [friend.user_id, new Set(shares.map((s) => s.device_id))] as const;
                }),
            );
            const sharesByFriendId = new Map<number, Set<string>>(shareEntries);

            renderPendingReceived(requests.received);
            renderPendingSent(requests.sent);
            if (window._friendRequestBannerRefresh) {
                void window._friendRequestBannerRefresh();
            }
            renderFriends(friends, ownedDevices, sharesByFriendId);
        } catch (err) {
            flash('error', err instanceof Error ? err.message : 'Failed to load friends.');
        }
    }

    addFormEl.addEventListener('submit', (event) => {
        event.preventDefault();
        const username = usernameInputEl.value.trim();
        if (!username) {
            flash('error', 'Enter a username.');
            return;
        }
        const autoAcceptReciprocal = autoAcceptInputEl.checked;
        const submitBtn = addFormEl.querySelector<HTMLButtonElement>('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
        }
        hideSuggestions();
        void (async () => {
            try {
                const resultStatus = await sendRequest(username, autoAcceptReciprocal);
                usernameInputEl.value = '';
                autoAcceptInputEl.checked = false;
                if (resultStatus === 'accepted') {
                    flash('success', `You are now friends with ${username}.`);
                } else {
                    flash('success', `Friend request sent to ${username}.`);
                }
                await refresh();
            } catch (err) {
                flash('error', err instanceof Error ? err.message : 'Could not send request.');
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                }
            }
        })();
    });

    return { refresh };
}

declare global {
    interface Window {
        initFriendsTab: typeof initFriendsTab;
        _friendsTabRefresh?: () => Promise<void>;
        _friendRequestBannerRefresh?: () => Promise<void>;
    }
}

window.initFriendsTab = initFriendsTab;

function bootstrapFriendsTab(): void {
    const friendsRoot = document.getElementById('friends-root');
    if (!friendsRoot || typeof window.showMessage !== 'function') {
        return;
    }
    const controller = initFriendsTab({
        root: friendsRoot,
        csrfToken: friendsRoot.dataset.csrfToken || '',
        currentUsername: friendsRoot.dataset.username || '',
        showMessage: window.showMessage,
    });
    window._friendsTabRefresh = controller.refresh;
    if (document.getElementById('tab-friends')?.classList.contains('active')) {
        void controller.refresh();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapFriendsTab);
} else {
    bootstrapFriendsTab();
}
