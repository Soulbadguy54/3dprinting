import { useEffect, useMemo, useState } from 'react'
import type { Game } from './data'

type PushConfig = { enabled: boolean; publicKey: string; devices: number }

function supportsWebPush(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function decodeVapidKey(encoded: string): Uint8Array<ArrayBuffer> {
  const padded = (encoded + '='.repeat((4 - encoded.length % 4) % 4))
    .replace(/-/g, '+').replace(/_/g, '/')
  const bytes = atob(padded)
  const output = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) output[i] = bytes.charCodeAt(i)
  return output
}

function requestBody(subscription: PushSubscription) {
  const json = subscription.toJSON()
  return JSON.stringify({
    endpoint: subscription.endpoint,
    keys: {
      p256dh: json.keys?.p256dh || '',
      auth: json.keys?.auth || '',
    },
  })
}

export async function disconnectPushForLogout(): Promise<void> {
  if (!supportsWebPush()) return
  const registration = await navigator.serviceWorker.getRegistration()
  const subscription = await registration?.pushManager.getSubscription()
  if (!subscription) return
  try {
    await fetch('/api/push/subscription', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: requestBody(subscription),
    })
  } finally {
    await subscription.unsubscribe()
  }
}

export default function PushSettings({ user, wishlistGames }: {
  user: string
  wishlistGames: Game[]
}) {
  const supported = supportsWebPush()
  const [config, setConfig] = useState<PushConfig | null>(null)
  const [permission, setPermission] = useState<NotificationPermission>(
    supported ? Notification.permission : 'default',
  )
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const sortedGames = useMemo(
    () => [...wishlistGames].sort((a, b) => (a.releaseDate || '9999').localeCompare(b.releaseDate || '9999')),
    [wishlistGames],
  )
  const [testGameId, setTestGameId] = useState<number | null>(null)
  const selectedGameId = sortedGames.some(game => game.id === testGameId)
    ? testGameId
    : (sortedGames[0]?.id ?? null)

  useEffect(() => {
    let cancelled = false
    setConfig(null)
    setConnected(false)
    setMessage('')
    const load = async () => {
      try {
        const response = await fetch('/api/push/config')
        if (!response.ok) throw new Error('Не удалось загрузить настройки уведомлений.')
        const result = await response.json() as PushConfig
        const subscription = supported
          ? await (await navigator.serviceWorker.ready).pushManager.getSubscription()
          : null
        if (cancelled) return
        setConfig(result)
        setConnected(Boolean(subscription && result.devices > 0))
        if (supported) setPermission(Notification.permission)
      } catch {
        if (!cancelled) setMessage('Не удалось проверить уведомления. Перезагрузи страницу.')
      }
    }
    void load()
    return () => { cancelled = true }
  }, [user, supported])

  const connect = async () => {
    if (!supported || !config?.enabled || busy) return
    setBusy(true)
    setMessage('')
    try {
      // Request permission from an actual button gesture, not on page load.
      const answer = Notification.permission === 'granted'
        ? 'granted'
        : await Notification.requestPermission()
      setPermission(answer)
      if (answer !== 'granted') {
        setMessage('Разреши уведомления для RateApp в настройках Edge и Android.')
        return
      }
      const registration = await navigator.serviceWorker.ready
      const subscription = await registration.pushManager.getSubscription()
        ?? await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decodeVapidKey(config.publicKey),
        })
      const response = await fetch('/api/push/subscription', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody(subscription),
      })
      if (!response.ok) {
        const result = await response.json().catch(() => null)
        throw new Error(result?.detail || 'Сервер не принял подписку.')
      }
      setConnected(true)
      setMessage('Это устройство подключено. Теперь можешь отправить тест.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Не получилось подключить уведомления.')
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    if (busy) return
    setBusy(true)
    setMessage('')
    try {
      await disconnectPushForLogout()
      setConnected(false)
      setMessage('Уведомления на этом устройстве выключены.')
    } catch {
      setMessage('Не удалось отключить уведомления. Попробуй снова.')
    } finally {
      setBusy(false)
    }
  }

  const sendTest = async () => {
    if (selectedGameId == null || busy) return
    setBusy(true)
    setMessage('')
    try {
      const response = await fetch('/api/push/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gameId: selectedGameId }),
      })
      const result = await response.json().catch(() => null)
      if (!response.ok) throw new Error(result?.detail || 'Отправка не удалась.')
      setMessage(`Push-сервис принял уведомление для ${result.accepted} устройства(устройств). Проверь уведомления Android.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Ошибка отправки тестового уведомления.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="info-card push-settings">
      <span className="eyebrow">УВЕДОМЛЕНИЯ</span>
      <h2>Релизы игр</h2>
      <p>В день выхода игры из «Хочу пройти» отправим push на подключённые устройства. Приложение может быть закрыто.</p>
      {!supported ? (
        <p className="push-settings__note">Этот браузер не поддерживает Web Push. Попробуй открыть установленный RateApp в Edge.</p>
      ) : !config?.enabled ? (
        <p className="push-settings__note">{config ? 'Уведомления пока недоступны на сервере.' : 'Загружаем настройки…'}</p>
      ) : (
        <>
          <div className="push-settings__status">
            <span>{connected && permission === 'granted' ? 'Уведомления на этом устройстве включены' : permission === 'denied' ? 'Уведомления запрещены в настройках браузера' : 'Уведомления не подключены'}</span>
            <span className="push-settings__dot" data-connected={connected && permission === 'granted'} />
          </div>
          <button className="push-settings__action" type="button" disabled={busy}
            onClick={() => { void (connected ? disconnect() : connect()) }}>
            {connected ? 'Отключить на этом устройстве' : 'Включить уведомления'}
          </button>
          <div className="push-settings__test">
            <strong>Проверка уведомления</strong>
            <p>Отправим сообщение так, словно выбранная игра вышла сегодня. Настоящая дата не изменится.</p>
            {sortedGames.length > 0 ? (
              <>
                <select value={selectedGameId ?? ''} onChange={e => setTestGameId(Number(e.target.value))}
                  aria-label="Игра для теста push-уведомления">
                  {sortedGames.map(game => <option key={game.id} value={game.id}>{game.title}</option>)}
                </select>
                <button className="push-settings__action" type="button"
                  onClick={() => { void sendTest() }} disabled={!connected || permission !== 'granted' || busy}>
                  Отправить тестовый push
                </button>
              </>
            ) : (
              <p className="push-settings__note">Добавь игру в «Хочу пройти», чтобы проверить уведомление.</p>
            )}
          </div>
        </>
      )}
      {message && <p className="push-settings__note" role="status">{message}</p>}
    </section>
  )
}
