import path from 'path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

import runtimeErrorOverlay from '@replit/vite-plugin-runtime-error-modal';

// Dev-server conveniences, with defaults. They used to be required for every
// command, so a production build failed unless leftover Replit variables were set.
const port = Number(process.env.PORT || 5173);
if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${process.env.PORT}"`);
}
const basePath = process.env.BASE_PATH || '/';

/**
 * A production build is what real people will load, so it must not quietly
 * fall back to anything. Without VITE_API_BASE_URL the app used to bake in
 * http://127.0.0.1:8000 - every user's own machine - and the privacy policy
 * shipped with its legal details blank.
 */
function assertProductionEnv(mode: string): void {
  const env = { ...loadEnv(mode, import.meta.dirname, 'VITE_'), ...process.env };
  const problems: string[] = [];
  const api = env.VITE_API_BASE_URL || '';
  if (!api.startsWith('https://')) {
    problems.push(`VITE_API_BASE_URL must be the backend's https:// address (got "${api}")`);
  }
  for (const key of [
    'VITE_POLICY_ORGANISATION',
    'VITE_POLICY_CONTACT_EMAIL',
    'VITE_POLICY_GRIEVANCE_OFFICER',
    'VITE_POLICY_DATA_LOCATION',
  ]) {
    if (!(env[key] || '').trim()) problems.push(`${key} is empty - the privacy policy must name it`);
  }
  if (problems.length) {
    throw new Error(`Refusing to build for production:\n  - ${problems.join('\n  - ')}`);
  }
}

export default defineConfig(async ({ command, mode }) => {
  if (command === 'build' && mode === 'production') assertProductionEnv(mode);
  return {
  base: basePath,
  plugins: [
    react(),
    tailwindcss(),
    runtimeErrorOverlay(),
    ...(process.env.NODE_ENV !== 'production' &&
    process.env.REPL_ID !== undefined
      ? [
          await import('@replit/vite-plugin-cartographer').then((m) =>
            m.cartographer({
              root: path.resolve(import.meta.dirname, '..'),
            }),
          ),
          await import('@replit/vite-plugin-dev-banner').then((m) =>
            m.devBanner(),
          ),
        ]
      : []),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
      '@assets': path.resolve(
        import.meta.dirname,
        '..',
        '..',
        'attached_assets',
      ),
    },
    dedupe: ['react', 'react-dom'],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, 'dist/public'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Libraries change far less often than the app, so a release does not
        // make every returning visitor download them again.
        manualChunks: {
          react: ['react', 'react-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
  server: {
    port,
    strictPort: true,
    host: '0.0.0.0',
    allowedHosts: true,
    fs: {
      strict: true,
    },
  },
  preview: {
    port,
    host: '0.0.0.0',
    allowedHosts: true,
  },
};
});
