/**
 * Live view state management module.
 * Manages the state for live mode including the skipHistoryFetch flag
 * that controls whether history is fetched after a reset.
 */

export interface LiveState {
    /** When true, skip fetching history and only show new incoming data */
    skipHistoryFetch: boolean;
    /** Timestamp of last known location */
    lastTimestamp: number | null;
    /** Count of events displayed */
    eventCount: number;
    /** Whether to fit bounds on next location update */
    needsFitBounds: boolean;
    /** Locations accumulated incrementally (by device) */
    incrementalLocations: Record<string, unknown[]>;
}

/**
 * Create initial live state.
 */
export function createInitialState(): LiveState {
    return {
        skipHistoryFetch: false,
        lastTimestamp: null,
        eventCount: 0,
        needsFitBounds: true,
        incrementalLocations: {},
    };
}

/**
 * Reset the live state for a fresh start.
 * After reset, only new incoming data should be displayed (no history fetch).
 * @param _state - Current state (unused, reset creates fresh state)
 * @returns New state after reset
 */
export function resetState(_state: LiveState): LiveState {
    return {
        skipHistoryFetch: true, // CRITICAL: Skip history fetch after reset
        lastTimestamp: Date.now() / 1000,
        eventCount: 0,
        needsFitBounds: true,
        incrementalLocations: {},
    };
}

/**
 * Check if history should be fetched.
 * Returns false if skipHistoryFetch is true (after reset).
 * @param state - Current state
 * @returns true if history should be fetched, false otherwise
 */
export function shouldFetchHistory(state: LiveState): boolean {
    return !state.skipHistoryFetch;
}

/**
 * Add a location incrementally to the state.
 * @param state - Current state
 * @param deviceName - Device name
 * @param location - Location data to add
 * @returns Updated state
 */
export function addIncrementalLocation(
    state: LiveState,
    deviceName: string,
    location: unknown
): LiveState {
    const deviceLocations = state.incrementalLocations[deviceName] || [];
    return {
        ...state,
        eventCount: state.eventCount + 1,
        incrementalLocations: {
            ...state.incrementalLocations,
            [deviceName]: [...deviceLocations, location],
        },
    };
}

/**
 * Clear the skipHistoryFetch flag to allow normal history fetching.
 * Used when switching modes or after initial page load.
 * @param state - Current state
 * @returns Updated state
 */
export function enableHistoryFetch(state: LiveState): LiveState {
    return {
        ...state,
        skipHistoryFetch: false,
    };
}
