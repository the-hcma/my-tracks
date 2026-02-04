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
            include: ['web_ui/static/web_ui/ts/utils.ts'],
            exclude: ['web_ui/static/web_ui/ts/**/*.test.ts'],
        },
    },
});
