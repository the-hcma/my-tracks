import { describe, expect, it } from 'vitest';

import { reconnectBackoffDelayMs, webSocketNeedsReconnect } from './webSocketReconnect';

describe('webSocketNeedsReconnect', () => {
    it('returns true when socket is null', () => {
        expect(webSocketNeedsReconnect(null)).toBe(true);
    });

    it('returns false when socket is open or connecting', () => {
        expect(webSocketNeedsReconnect({ readyState: WebSocket.OPEN } as WebSocket)).toBe(false);
        expect(webSocketNeedsReconnect({ readyState: WebSocket.CONNECTING } as WebSocket)).toBe(false);
    });

    it('returns true when socket is closed or closing', () => {
        expect(webSocketNeedsReconnect({ readyState: WebSocket.CLOSED } as WebSocket)).toBe(true);
        expect(webSocketNeedsReconnect({ readyState: WebSocket.CLOSING } as WebSocket)).toBe(true);
    });
});

describe('reconnectBackoffDelayMs', () => {
    it('uses exponential backoff from base delay', () => {
        expect(reconnectBackoffDelayMs(1, 3000)).toBe(3000);
        expect(reconnectBackoffDelayMs(2, 3000)).toBe(6000);
        expect(reconnectBackoffDelayMs(5, 3000)).toBe(48000);
    });
});
