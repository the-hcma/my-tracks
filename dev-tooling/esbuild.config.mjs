/**
 * esbuild configuration for My Tracks frontend.
 *
 * Compiles TypeScript to JavaScript with bundling and minification.
 */

import * as esbuild from 'esbuild';
import { existsSync, mkdirSync } from 'fs';
import { dirname } from 'path';

const isWatch = process.argv.includes('--watch');

const outDir = 'web_ui/static/web_ui/js';

// Ensure output directory exists
if (!existsSync(outDir)) {
    mkdirSync(outDir, { recursive: true });
}

/** @type {esbuild.BuildOptions} */
const buildOptions = {
    entryPoints: ['web_ui/static/web_ui/ts/main.ts'],
    bundle: true,
    outfile: `${outDir}/main.js`,
    format: 'iife',
    target: ['es2022', 'chrome100', 'firefox100', 'safari15'],
    minify: !isWatch,
    sourcemap: isWatch,
    logLevel: 'info',
    external: [],
    define: {
        'process.env.NODE_ENV': isWatch ? '"development"' : '"production"',
    },
};

async function build() {
    if (isWatch) {
        const ctx = await esbuild.context(buildOptions);
        await ctx.watch();
        console.log('Watching for changes...');
    } else {
        const result = await esbuild.build(buildOptions);
        console.log('Build complete:', result);
    }
}

build().catch((err) => {
    console.error('Build failed:', err);
    process.exit(1);
});
