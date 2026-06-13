/**
 * Orchestration for loading Last Known locations into live activity.
 * Serialized and generation-guarded so stale fetches cannot overwrite newer results.
 */

import {
    fetchLastKnownLocations,
    LastKnownFetchError,
    planLastKnownUiUpdate,
    type LocationWithDeviceName,
} from './liveActivityToolbar';
import { unregisterAllServiceWorkers } from './serviceWorkerRecovery';

export type LastKnownLoadResult = 'success' | 'empty' | 'error' | 'stale';

export interface LastKnownLoadLocation extends LocationWithDeviceName {
    id?: number | null;
}

export interface LastKnownLoadDeps<T extends LastKnownLoadLocation> {
    fetchFn: typeof fetch;
    isStaff: boolean;
    visibleDeviceNames: readonly string[];
    skipHistoryFetch: boolean;
    renderedDeviceNames: Iterable<string>;
    extractResults: (data: unknown) => T[];
    waitForRefresh?: () => Promise<void>;
}

export interface LastKnownLoadCallbacks<T extends LastKnownLoadLocation> {
    onReplace: (locations: T[]) => void;
    onEmpty: () => void;
    onError: (message: string) => void;
}

export function lastKnownFetchErrorMessage(error: LastKnownFetchError): string {
    if (error.kind === 'json') {
        return 'Last Known: server returned an invalid response.';
    }
    if (error.kind === 'http') {
        return `Last Known: fetch failed (${error.status}).`;
    }
    const detail = error.causeMessage ? `: ${error.causeMessage}` : '';
    return `Last Known: fetch failed (network error${detail}).`;
}

let lastKnownLoadGeneration = 0;
let lastKnownLoadInFlight: Promise<LastKnownLoadResult> | null = null;

/** Reset module state between vitest cases. */
export function resetLastKnownLoadStateForTests(): void {
    lastKnownLoadGeneration = 0;
    lastKnownLoadInFlight = null;
}

export async function runLastKnownLoad<T extends LastKnownLoadLocation>(
    deps: LastKnownLoadDeps<T>,
    callbacks: LastKnownLoadCallbacks<T>,
): Promise<LastKnownLoadResult> {
    const generation = ++lastKnownLoadGeneration;
    const run = async (): Promise<LastKnownLoadResult> => {
        if (deps.waitForRefresh) {
            await deps.waitForRefresh();
            if (generation !== lastKnownLoadGeneration) {
                return 'stale';
            }
        }

        const renderedDeviceNames = new Set(deps.renderedDeviceNames);
        try {
            const locations = await fetchLastKnownLocationsWithRecovery(deps);

            if (generation !== lastKnownLoadGeneration) {
                return 'stale';
            }

            if (locations.length === 0) {
                callbacks.onEmpty();
                return 'empty';
            }

            const plan = planLastKnownUiUpdate({
                locations,
                skipHistoryFetch: deps.skipHistoryFetch,
                renderedDeviceCount: renderedDeviceNames.size,
                renderedDeviceNames,
            });

            if (generation !== lastKnownLoadGeneration || plan.mergeStrategy !== 'replace') {
                return 'stale';
            }

            callbacks.onReplace(plan.locations);
            return 'success';
        } catch (error) {
            if (generation !== lastKnownLoadGeneration) {
                return 'stale';
            }
            if (error instanceof LastKnownFetchError) {
                callbacks.onError(lastKnownFetchErrorMessage(error));
            } else {
                callbacks.onError('Last Known: unexpected error while loading locations.');
            }
            return 'error';
        }
    };

    const promise = run();
    lastKnownLoadInFlight = promise.finally(() => {
        if (lastKnownLoadInFlight === promise) {
            lastKnownLoadInFlight = null;
        }
    });
    return promise;
}

async function fetchLastKnownLocationsWithRecovery<T extends LastKnownLoadLocation>(
    deps: LastKnownLoadDeps<T>,
    attempt = 0,
): Promise<T[]> {
    try {
        return await fetchLastKnownLocations<T>({
            fetchFn: deps.fetchFn,
            isStaff: deps.isStaff,
            visibleDeviceNames: deps.visibleDeviceNames,
            extractResults: deps.extractResults,
        });
    } catch (error) {
        const canRecoverFromServiceWorker =
            attempt === 0 &&
            error instanceof LastKnownFetchError &&
            error.kind === 'network' &&
            typeof navigator !== 'undefined' &&
            'serviceWorker' in navigator;

        if (canRecoverFromServiceWorker) {
            const removed = await unregisterAllServiceWorkers();
            if (removed > 0) {
                return fetchLastKnownLocationsWithRecovery(deps, attempt + 1);
            }
        }
        throw error;
    }
}
