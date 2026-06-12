import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        environment: 'jsdom',
        include: ['web_ui/static/web_ui/ts/**/*.test.ts'],
        globals: true,
        coverage: {
            provider: 'v8',
            reporter: ['text', 'html'],
            // Only measure coverage on utility modules (not main.ts which requires full DOM)
            include: [
                'web_ui/static/web_ui/ts/utils.ts',
                'web_ui/static/web_ui/ts/messages.ts',
                'web_ui/static/web_ui/ts/friends.ts',
                'web_ui/static/web_ui/ts/friend-request-banner.ts',
                'web_ui/static/web_ui/ts/liveActivity.ts',
                'web_ui/static/web_ui/ts/liveActivityToolbar.ts',
            ],
            exclude: ['web_ui/static/web_ui/ts/**/*.test.ts'],
        },
    },
});
