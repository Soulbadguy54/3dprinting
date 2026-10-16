import { useEffect, useState } from 'react'

/** Offer the new service worker without forcibly reloading an in-progress edit. */
export default function PwaUpdateNotice({ onUpdate }: { onUpdate: () => void }) {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const onAvailable = () => setReady(true)
    window.addEventListener('rateapp:update-available', onAvailable)
    return () => window.removeEventListener('rateapp:update-available', onAvailable)
  }, [])
  if (!ready) return null
  return (
    <aside className="pwa-update-notice" role="status">
      <span>Доступна новая версия RateApp</span>
      <button type="button" onClick={onUpdate}>Обновить</button>
      <button type="button" aria-label="Закрыть уведомление" onClick={() => setReady(false)}>×</button>
    </aside>
  )
}
