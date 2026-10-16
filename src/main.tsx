import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App'
import InstallPrompt from './InstallPrompt'
import DesktopGate from './DesktopGate'
import InstallPage from './InstallPage'
import PwaUpdateNotice from './PwaUpdateNotice'
import AppErrorBoundary from './AppErrorBoundary'
import './collectionCards.css'
import './ratingWheel.css'
import './styles.css'

// Installed PWAs can stay open in the background for days. Check for a fresh
// service worker when they return to the foreground instead of leaving old
// CSS/JS cached until the next full browser launch.
const updatePwa = registerSW({
  immediate: true,
  onNeedRefresh() {
    window.dispatchEvent(new Event('rateapp:update-available'))
  },
  onRegisteredSW(_swUrl, registration) {
    if (!registration) return
    let lastCheck = 0
    const checkForUpdates = () => {
      if (document.visibilityState !== 'visible' || !navigator.onLine) return
      if (Date.now() - lastCheck < 60_000) return
      lastCheck = Date.now()
      void registration.update().catch(() => {
        // Offline/restricted networks shouldn't interrupt the app itself.
      })
    }
    document.addEventListener('visibilitychange', checkForUpdates)
    window.addEventListener('focus', checkForUpdates)
  },
})

// Load browser error tracking only if configured; it never blocks the app.
if (import.meta.env.VITE_SENTRY_DSN) {
  void import('@sentry/react').then(({ init }) => init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.MODE,
    sendDefaultPii: false,
    tracesSampleRate: 0,
  })).catch(() => {})
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      {window.location.pathname.replace(/\/+$/, '') === '/install'
        ? <InstallPage />
        : <DesktopGate>
            <App />
            <InstallPrompt />
            <PwaUpdateNotice onUpdate={() => { void updatePwa(true) }} />
          </DesktopGate>}
    </AppErrorBoundary>
  </StrictMode>,
)
