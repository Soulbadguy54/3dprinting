import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App'
import InstallPrompt from './InstallPrompt'
import DesktopGate from './DesktopGate'
import InstallPage from './InstallPage'
import './collectionCards.css'
import './styles.css'

// Installed PWAs can stay open in the background for days. Check for a fresh
// service worker when they return to the foreground instead of leaving old
// CSS/JS cached until the next full browser launch.
registerSW({
  immediate: true,
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {window.location.pathname.replace(/\/+$/, '') === '/install'
      ? <InstallPage />
      : <DesktopGate>
          <App />
          <InstallPrompt />
        </DesktopGate>}
  </StrictMode>,
)
