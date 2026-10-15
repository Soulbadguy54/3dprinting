import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// @ts-expect-error: Node's runtime modules are available to Vite but this frontend tsconfig omits @types/node.
import { readFileSync, writeFileSync } from 'node:fs'
// @ts-expect-error: Node's runtime modules are available to Vite but this frontend tsconfig omits @types/node.
import { fileURLToPath } from 'node:url'
import { VitePWA } from 'vite-plugin-pwa'

// The source bitmap is the user's approved frame-free icon. Embed it in SVG
// for a resolution-independent PWA icon in addition to the 192px PNG.
const publicDir = fileURLToPath(new URL('./public/', import.meta.url))
const iconPngBase64 = readFileSync(publicDir + 'rateapp-icon-192.png').toString('base64')
writeFileSync(
  publicDir + 'rateapp-icon.svg',
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><image width="512" height="512" href="data:image/png;base64,${iconPngBase64}"/></svg>`,
)

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['rateapp-icon-192.png', 'rateapp-icon.svg', 'rateapp-loading-gamepad.avif', 'push-sw.js'],
      workbox: {
        navigateFallbackDenylist: [/^\/api\//],
        importScripts: ['/push-sw.js'],
      },
      manifest: {
        name: 'RateApp',
        short_name: 'RateApp',
        description: 'Личная коллекция, оценки и игровой дневник',
        theme_color: '#0b0d12',
        background_color: '#0b0d12',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          {
            src: '/rateapp-icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any'
          },
          {
            src: '/rateapp-icon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any'
          }
        ]
      }
    })
  ]
})
