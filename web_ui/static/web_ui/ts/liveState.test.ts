/**
 * Tests for live view state management.
 * These tests verify the critical reset behavior:
 * After reset, only new incoming data should be displayed (no history fetch).
 */
import { describe, it, expect } from 'vitest';
import {
    createInitialState,
    resetState,
    shouldFetchHistory,
    addIncrementalLocation,
    enableHistoryFetch,
    LiveState,
} from './liveState';

describe('liveState', () => {
    describe('createInitialState', () => {
        it('creates state with skipHistoryFetch=false by default', () => {
            const state = createInitialState();
            expect(state.skipHistoryFetch).toBe(false);
        });

        it('creates state with empty incremental locations', () => {
            const state = createInitialState();
            expect(state.incrementalLocations).toEqual({});
        });

        it('creates state with eventCount=0', () => {
            const state = createInitialState();
            expect(state.eventCount).toBe(0);
        });
    });

    describe('resetState', () => {
        it('sets skipHistoryFetch=true after reset', () => {
            const initial = createInitialState();
            const afterReset = resetState(initial);
            
            // CRITICAL: After reset, we should NOT fetch history
            expect(afterReset.skipHistoryFetch).toBe(true);
        });

        it('clears incremental locations after reset', () => {
            const initial: LiveState = {
                ...createInitialState(),
                incrementalLocations: {
                    'device1': [{ lat: 1, lon: 2 }],
                    'device2': [{ lat: 3, lon: 4 }],
                },
            };
            const afterReset = resetState(initial);
            
            expect(afterReset.incrementalLocations).toEqual({});
        });

        it('resets eventCount to 0', () => {
            const initial: LiveState = {
                ...createInitialState(),
                eventCount: 42,
            };
            const afterReset = resetState(initial);
            
            expect(afterReset.eventCount).toBe(0);
        });

        it('sets lastTimestamp to current time', () => {
            const before = Date.now() / 1000;
            const afterReset = resetState(createInitialState());
            const after = Date.now() / 1000;
            
            expect(afterReset.lastTimestamp).toBeGreaterThanOrEqual(before);
            expect(afterReset.lastTimestamp).toBeLessThanOrEqual(after);
        });

        it('sets needsFitBounds=true so next location centers the map', () => {
            const initial: LiveState = {
                ...createInitialState(),
                needsFitBounds: false,
            };
            const afterReset = resetState(initial);
            
            expect(afterReset.needsFitBounds).toBe(true);
        });
    });

    describe('shouldFetchHistory', () => {
        it('returns true when skipHistoryFetch=false (normal operation)', () => {
            const state = createInitialState();
            expect(shouldFetchHistory(state)).toBe(true);
        });

        it('returns false when skipHistoryFetch=true (after reset)', () => {
            const state = resetState(createInitialState());
            
            // CRITICAL: After reset, shouldFetchHistory must return false
            expect(shouldFetchHistory(state)).toBe(false);
        });
    });

    describe('addIncrementalLocation', () => {
        it('adds location to correct device', () => {
            const state = resetState(createInitialState());
            const location = { lat: 40.7128, lon: -74.0060 };
            
            const newState = addIncrementalLocation(state, 'iPhone', location);
            
            expect(newState.incrementalLocations['iPhone']).toEqual([location]);
        });

        it('appends to existing locations for device', () => {
            let state = resetState(createInitialState());
            const loc1 = { lat: 40.7128, lon: -74.0060 };
            const loc2 = { lat: 40.7130, lon: -74.0062 };
            
            state = addIncrementalLocation(state, 'iPhone', loc1);
            state = addIncrementalLocation(state, 'iPhone', loc2);
            
            expect(state.incrementalLocations['iPhone']).toEqual([loc1, loc2]);
        });

        it('tracks locations for multiple devices separately', () => {
            let state = resetState(createInitialState());
            const loc1 = { lat: 40.7128, lon: -74.0060 };
            const loc2 = { lat: 34.0522, lon: -118.2437 };
            
            state = addIncrementalLocation(state, 'iPhone', loc1);
            state = addIncrementalLocation(state, 'Android', loc2);
            
            expect(state.incrementalLocations['iPhone']).toEqual([loc1]);
            expect(state.incrementalLocations['Android']).toEqual([loc2]);
        });

        it('increments eventCount', () => {
            let state = resetState(createInitialState());
            expect(state.eventCount).toBe(0);
            
            state = addIncrementalLocation(state, 'iPhone', { lat: 1, lon: 2 });
            expect(state.eventCount).toBe(1);
            
            state = addIncrementalLocation(state, 'iPhone', { lat: 3, lon: 4 });
            expect(state.eventCount).toBe(2);
        });
    });

    describe('enableHistoryFetch', () => {
        it('clears skipHistoryFetch flag', () => {
            const state = resetState(createInitialState());
            expect(state.skipHistoryFetch).toBe(true);
            
            const enabled = enableHistoryFetch(state);
            expect(enabled.skipHistoryFetch).toBe(false);
        });

        it('preserves other state when enabling history fetch', () => {
            let state = resetState(createInitialState());
            state = addIncrementalLocation(state, 'iPhone', { lat: 1, lon: 2 });
            
            const enabled = enableHistoryFetch(state);
            
            expect(enabled.incrementalLocations['iPhone']).toEqual([{ lat: 1, lon: 2 }]);
            expect(enabled.eventCount).toBe(1);
        });
    });

    describe('reset workflow', () => {
        it('complete reset workflow: reset -> receive locations -> only new data shown', () => {
            // 1. Start with initial state (normal mode, can fetch history)
            let state = createInitialState();
            expect(shouldFetchHistory(state)).toBe(true);
            
            // 2. User clicks reset
            state = resetState(state);
            
            // 3. CRITICAL: After reset, history fetch should be skipped
            expect(shouldFetchHistory(state)).toBe(false);
            expect(state.incrementalLocations).toEqual({});
            expect(state.eventCount).toBe(0);
            
            // 4. New location arrives via WebSocket
            const newLocation = { lat: 40.7128, lon: -74.0060, timestamp: Date.now() };
            state = addIncrementalLocation(state, 'iPhone', newLocation);
            
            // 5. Verify only the new location is tracked (no history)
            expect(state.incrementalLocations['iPhone']).toHaveLength(1);
            expect(state.incrementalLocations['iPhone'][0]).toEqual(newLocation);
            expect(state.eventCount).toBe(1);
            
            // 6. History fetch should still be skipped until explicitly enabled
            expect(shouldFetchHistory(state)).toBe(false);
        });
    });
});
