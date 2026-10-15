import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App'
import InstallPrompt from './InstallPrompt'
import DesktopGate from './DesktopGate'
import InstallPage from './InstallPage'
import './styles.css'

registerSW({ immediate: true })

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
