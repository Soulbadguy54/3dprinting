import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'

const DISMISS_KEY = 'rateapp-install-dismiss-until'
const INSTALLED_KEY = 'rateapp-install-confirmed'
const DISMISS_DAYS = 14

type InstallChoice = { outcome: 'accepted' | 'dismissed'; platform: string }
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<InstallChoice>
}
type RelatedApplication = { platform?: string; id?: string; url?: string }
type InstallNavigator = Navigator & {
  standalone?: boolean
  getInstalledRelatedApps?: () => Promise<RelatedApplication[]>
}
type Platform = 'ios-safari' | 'ios-other' | 'android' | 'other'

function identifyPlatform(): Platform {
  const ua = navigator.userAgent
  const ios = /iPad|iPhone|iPod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  if (ios) {
    return /CriOS|FxiOS|EdgiOS|OPiOS|DuckDuckGo/i.test(ua) ? 'ios-other' : 'ios-safari'
  }
  return /Android/i.test(ua) ? 'android' : 'other'
}

function isRunningInstalled(): boolean {
  const nav = navigator as InstallNavigator
  return nav.standalone === true ||
    ['standalone', 'fullscreen', 'minimal-ui'].some((mode) => window.matchMedia(`(display-mode: ${mode})`).matches) ||
    document.referrer.startsWith('android-app://')
}

function isInstallSuppressed(): boolean {
  try {
    return localStorage.getItem(INSTALLED_KEY) === 'yes' ||
      Number(localStorage.getItem(DISMISS_KEY) || 0) > Date.now()
  } catch {
    return false
  }
}

function rememberInstalled(): void {
  try {
    localStorage.setItem(INSTALLED_KEY, 'yes')
    localStorage.removeItem(DISMISS_KEY)
  } catch { /* Storage can be blocked by browser settings. */ }
}

function rememberDismissed(): void {
  try {
    localStorage.setItem(DISMISS_KEY, String(Date.now() + DISMISS_DAYS * 24 * 60 * 60 * 1000))
  } catch { /* Keep the prompt dismissible within this session. */ }
}

export default function InstallPrompt() {
  const reduceMotion = useReducedMotion()
  const [platform] = useState<Platform>(identifyPlatform)
  const [ready, setReady] = useState(false)
  const [hidden, setHidden] = useState(() => isRunningInstalled() || isInstallSuppressed())
  const [instructions, setInstructions] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [nativeAvailable, setNativeAvailable] = useState(false)
  const promptRef = useRef<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    if (hidden) return

    let alive = true
    let checkedRelatedApps = false
    let relatedAppsCheckPending = false
    const revealIfNeeded = () => {
      if (alive && !isRunningInstalled() && !isInstallSuppressed()) setReady(true)
    }
    const visibilityTimer = window.setTimeout(() => {
      if (!relatedAppsCheckPending) revealIfNeeded()
    }, 1000)
    // Never leave the invitation permanently hidden if the browser's
    // installed-related-apps API does not respond.
    const maxVisibilityTimer = window.setTimeout(revealIfNeeded, 3000)

    const onInstallAvailable = (event: Event) => {
      event.preventDefault()
      promptRef.current = event as BeforeInstallPromptEvent
      setNativeAvailable(true)
      setInstructions(false)
      if (!relatedAppsCheckPending && checkedRelatedApps) revealIfNeeded()
    }
    const onInstalled = () => {
      rememberInstalled()
      promptRef.current = null
      if (alive) setHidden(true)
    }
    const onDisplayModeChange = () => {
      if (isRunningInstalled()) {
        rememberInstalled()
        if (alive) setHidden(true)
      }
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') onDisplayModeChange()
    }

    window.addEventListener('beforeinstallprompt', onInstallAvailable)
    window.addEventListener('appinstalled', onInstalled)
    document.addEventListener('visibilitychange', onVisibilityChange)
    const standalone = window.matchMedia('(display-mode: standalone)')
    standalone.addEventListener?.('change', onDisplayModeChange)

    // Chrome on Android can report an installed WebAPK even when this site
    // is being viewed in an ordinary browser tab (which is not standalone).
    const nav = navigator as InstallNavigator
    if (typeof nav.getInstalledRelatedApps === 'function') {
      relatedAppsCheckPending = true
      void nav.getInstalledRelatedApps().then((apps) => {
        if (!alive) return
        if (apps.some((app) => app.platform === 'webapp')) onInstalled()
      }).catch(() => { /* Unsupported or denied: use display-mode instead. */ })
        .finally(() => {
          relatedAppsCheckPending = false
          checkedRelatedApps = true
          if (alive) revealIfNeeded()
        })
    } else {
      checkedRelatedApps = true
    }

    return () => {
      alive = false
      window.clearTimeout(visibilityTimer)
      window.clearTimeout(maxVisibilityTimer)
      window.removeEventListener('beforeinstallprompt', onInstallAvailable)
      window.removeEventListener('appinstalled', onInstalled)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      standalone.removeEventListener?.('change', onDisplayModeChange)
    }
  }, [hidden])

  const dismiss = () => {
    rememberDismissed()
    setHidden(true)
  }

  const markAlreadyInstalled = () => {
    rememberInstalled()
    setHidden(true)
  }

  const install = async () => {
    if (installing) return
    const event = promptRef.current
    if (!event) {
      setInstructions(true)
      return
    }

    // Must execute directly within the user gesture on Chromium Android.
    promptRef.current = null
    setNativeAvailable(false)
    setInstalling(true)
    try {
      await event.prompt()
      const choice = await event.userChoice
      if (choice.outcome === 'accepted') {
        rememberInstalled()
        setHidden(true)
      } else {
        dismiss()
      }
    } catch {
      // The native prompt might stop working or become unavailable.
      setInstructions(true)
    } finally {
      setInstalling(false)
    }
  }

  const ios = platform === 'ios-safari' || platform === 'ios-other'
  const manualHint = platform === 'ios-other'
    ? 'Открой эту страницу в Safari, нажми «Поделиться», затем «На экран Домой» и «Добавить».'
    : platform === 'ios-safari'
      ? 'Нажми «Поделиться» (квадрат со стрелкой вверх), выбери «На экран Домой» и затем «Добавить».'
      : 'Открой меню браузера ⋮ и выбери «Установить приложение» или «Добавить на главный экран».'

  return (
    <AnimatePresence>
      {ready && !hidden && (platform !== 'other' || nativeAvailable) && (
        <motion.aside
          className="install-prompt"
          role="region"
          aria-label="Установка RateApp"
          initial={reduceMotion ? false : { opacity: 0, y: 22, scale: .98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reduceMotion ? undefined : { opacity: 0, y: 20 }}
          transition={{ type: 'spring', stiffness: 360, damping: 31 }}
        >
          <div className="install-prompt__header">
            <img src="/rateapp-icon-192.png" width={48} height={48} alt="" className="install-prompt__icon" />
            <div className="install-prompt__heading">
              <strong>Установи RateApp</strong>
              <span>Игровая библиотека прямо на главном экране телефона</span>
            </div>
            <button type="button" className="install-prompt__close" onClick={dismiss} aria-label="Закрыть предложение установки" title="Не сейчас">
              <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg>
            </button>
          </div>

          {instructions && (
            <div className="install-prompt__instructions">
              <p>{manualHint}</p>
              {ios && <span>На iPhone установка происходит через меню браузера, без системной кнопки установки.</span>}
            </div>
          )}
          <div className="install-prompt__actions">
            <button type="button" className="install-prompt__primary" onClick={instructions ? dismiss : () => { void install() }} disabled={installing}>
              {installing ? 'Открываем установку…' : instructions ? 'Понятно' : 'Установить'}
            </button>
            <button type="button" className="install-prompt__secondary" onClick={instructions ? markAlreadyInstalled : dismiss}>
              {instructions ? 'Уже установлено' : 'Не сейчас'}
            </button>
          </div>
          {!instructions && (
            <button type="button" className="install-prompt__already" onClick={markAlreadyInstalled}>
              Уже установлено?
            </button>
          )}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
