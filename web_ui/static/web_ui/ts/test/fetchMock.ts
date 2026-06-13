/** Shared fetch() mock for Last Known vitest suites. */
export function jsonFetchResponse(
    body: unknown,
    ok = true,
    status = 200,
): {
    ok: boolean;
    status: number;
    text: () => Promise<string>;
} {
    return {
        ok,
        status,
        text: async () => JSON.stringify(body),
    };
}
