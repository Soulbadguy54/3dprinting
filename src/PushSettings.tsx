import { useEffect, useRef, useState } from 'react'

type PushConfig = { enabled: boolean; publicKey: string; devices: number }
type PushState = { config: PushConfig; subscribed: boolean; permission: NotificationPermission }
const PUSH_CHANGED_EVENT = 'rateapp:push-changed'

function supportsWebPush(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function rememberChoice(user: string): void {
  try { window.localStorage.setItem(`rateapp:push-invite:v1:${user}`, 'seen') } catch { /* Private browsing. */ }
}

function hasSeenInvite(user: string): boolean {
  try { return window.localStorage.getItem(`rateapp:push-invite:v1:${user}`) === 'seen' } catch { return false }
}

function decodeVapidKey(encoded: string): Uint8Array<ArrayBuffer> {
  const padded = (encoded + '='.repeat((4 - encoded.length % 4) % 4))
    .replace(/-/g, '+').replace(/_/g, '/')
  const bytes = atob(padded)
  const output = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) output[i] = bytes.charCodeAt(i)
  return output
}

function requestBody(subscription: PushSubscription): string {
  const json = subscription.toJSON()
  return JSON.stringify({
    endpoint: subscription.endpoint,
    keys: {
      p256dh: json.keys?.p256dh || '',
      auth: json.keys?.auth || '',
    },
  })
}

async function readPushState(): Promise<PushState> {
  const response = await fetch('/api/push/config')
  if (!response.ok) throw new Error('Не удалось проверить настройки уведомлений.')
  const config = await response.json() as PushConfig
  const permission = supportsWebPush() ? Notification.permission : 'default'
  const registration = supportsWebPush() ? await navigator.serviceWorker.ready : null
  const subscription = await registration?.pushManager.getSubscription()
  return { config, permission, subscribed: Boolean(subscription && config.devices > 0) }
}

/** Must be called directly from a click handler before any other await. */
async function enablePush(publicKey: string): Promise<void> {
  if (!supportsWebPush()) throw new Error('Браузер не поддерживает push-уведомления.')
  const permission = Notification.permission === 'granted'
    ? 'granted'
    : await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error('Разреши уведомления для RateApp в настройках браузера и телефона.')
  }

  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
    ?? await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: decodeVapidKey(publicKey),
    })
  const response = await fetch('/api/push/subscription', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: requestBody(subscription),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(payload?.detail || 'Не удалось подключить уведомления.')
  }
  window.dispatchEvent(new Event(PUSH_CHANGED_EVENT))
}

export async function disconnectPushForLogout(): Promise<void> {
  if (!supportsWebPush()) return
  const registration = await navigator.serviceWorker.getRegistration()
  const subscription = await registration?.pushManager.getSubscription()
  if (!subscription) return
  const response = await fetch('/api/push/subscription', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: requestBody(subscription),
  })
  if (!response.ok) throw new Error('Не удалось отключить подписку.')
  await subscription.unsubscribe()
  window.dispatchEvent(new Event(PUSH_CHANGED_EVENT))
}

export default function PushSettings({ user }: { user: string }) {
  const supported = supportsWebPush()
  const [state, setState] = useState<PushState | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let active = true
    const refresh = () => {
      void readPushState().then(next => {
        if (active) setState(next)
      }).catch(() => {
        if (active) setMessage('Не удалось проверить уведомления.')
      })
    }
    refresh()
    window.addEventListener(PUSH_CHANGED_EVENT, refresh)
    window.addEventListener('focus', refresh)
    return () => {
      active = false
      window.removeEventListener(PUSH_CHANGED_EVENT, refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [user])

  const enabled = state?.subscribed === true && state.permission === 'granted'
  const toggle = async () => {
    if (!state?.config.enabled || !supported || busy) return
    setBusy(true)
    setMessage('')
    try {
      if (enabled) {
        await disconnectPushForLogout()
      } else {
        await enablePush(state.config.publicKey)
      }
      rememberChoice(user)
      setState(await readPushState())
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Не удалось изменить настройки.')
      setState(await readPushState().catch(() => state))
    } finally {
      setBusy(false)
    }
  }

  const iosHelp = /iPad|iPhone|iPod/.test(navigator.userAgent)
    ? 'На iPhone уведомления доступны для приложения, добавленного на экран «Домой».'
    : 'Включить уведомления можно в установленном RateApp.'

  return (
    <section className="info-card push-settings" aria-label="Настройки уведомлений">
      <span className="eyebrow">УВЕДОМЛЕНИЯ</span>
      <div className="push-settings__row">
        <div className="push-settings__text">
          <h2>Релизы игр</h2>
          <p>Уведомим в день выхода игры из «Хочу пройти».</p>
        </div>
        <button
          type="button"
          className="push-switch"
          role="switch"
          aria-label="Уведомления о выходе игр"
          aria-checked={enabled}
          disabled={!supported || !state?.config.enabled || busy}
          onClick={() => { void toggle() }}
        >
          <span className="push-switch__track"><span className="push-switch__thumb" /></span>
        </button>
      </div>
      {!supported && <p className="push-settings__note">{iosHelp}</p>}
      {supported && state && !state.config.enabled && <p className="push-settings__note">Уведомления временно недоступны.</p>}
      {supported && state?.permission === 'denied' && !enabled &&
        <p className="push-settings__note">Разреши уведомления в настройках браузера или телефона.</p>}
      {message && <p className="push-settings__note" role="status">{message}</p>}
    </section>
  )
}

export function PushOnboarding({ user }: { user: string }) {
  const [config, setConfig] = useState<PushConfig | null>(null)
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let active = true
    setVisible(false)
    if (!supportsWebPush() || hasSeenInvite(user) || Notification.permission === 'denied') return
    void readPushState().then(state => {
      if (!active) return
      if (state.config.enabled && !state.subscribed) {
        setConfig(state.config)
        setVisible(true)
      }
    }).catch(() => { /* Do not interrupt entry if push settings cannot be loaded. */ })
    return () => { active = false }
  }, [user])

  useEffect(() => {
    if (!visible) return
    buttonRef.current?.focus()
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismiss()
    }
    window.addEventListener('keydown', onEscape)
    return () => window.removeEventListener('keydown', onEscape)
  }, [visible, user])

  const dismiss = () => {
    rememberChoice(user)
    setVisible(false)
  }

  const accept = async () => {
    if (!config || busy) return
    setBusy(true)
    setMessage('')
    try {
      await enablePush(config.publicKey)
      dismiss()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Не удалось подключить уведомления.')
      if (supportsWebPush() && Notification.permission === 'denied') rememberChoice(user)
    } finally {
      setBusy(false)
    }
  }

  if (!visible) return null
  return (
    <div className="push-invite__backdrop">
      <section className="push-invite" role="dialog" aria-modal="true"
        aria-labelledby="push-invite-title" aria-describedby="push-invite-description">
        <div className="push-invite__icon" aria-hidden="true">
          <svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
            <path d="M10 21h4" />
          </svg>
        </div>
        <h2 id="push-invite-title">Не пропусти выход игры</h2>
        <p id="push-invite-description">Напомним, когда выйдет игра из твоего списка «Хочу пройти».</p>
        <button ref={buttonRef} type="button" className="push-invite__allow" disabled={busy}
          onClick={() => { void accept() }}>
          {busy ? 'Подключаем…' : 'Включить уведомления'}
        </button>
        <button type="button" className="push-invite__later" disabled={busy} onClick={dismiss}>
          Не сейчас
        </button>
        {message && <p className="push-settings__note" role="status">{message}</p>}
      </section>
    </div>
  )
}
