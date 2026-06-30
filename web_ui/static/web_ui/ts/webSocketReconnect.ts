/**
 * Live dashboard WebSocket reconnect helpers (focus/visibility driven).
 */

/** True when the client should open a new WebSocket (not OPEN or CONNECTING). */
export function webSocketNeedsReconnect(ws: WebSocket | null): boolean {
    if (ws === null) {
        return true;
    }
    const state = ws.readyState;
    return state === WebSocket.CLOSED || state === WebSocket.CLOSING;
}

/** Exponential backoff delay for reconnect attempt n (1-based), in milliseconds. */
export function reconnectBackoffDelayMs(attempt: number, baseDelayMs: number): number {
    if (attempt < 1) {
        return baseDelayMs;
    }
    return baseDelayMs * Math.pow(2, attempt - 1);
}
