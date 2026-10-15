import { useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'

type NativeInstallEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}
type PwaNavigator = Navigator & {
  standalone?: boolean
  getInstalledRelatedApps?: () => Promise<Array<{ platform: string }>>
}

function platformType(): 'ios' | 'android' | 'desktop' {
  const ua = navigator.userAgent
  if (/iPhone|iPad|iPod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) return 'ios'
  return /Android/i.test(ua) ? 'android' : 'desktop'
}

function launchedAsApp(): boolean {
  const nav = navigator as PwaNavigator
  return nav.standalone === true ||
    ['standalone', 'fullscreen', 'minimal-ui'].some((mode) => window.matchMedia(`(display-mode: ${mode})`).matches)
}

export default function InstallPage() {
  const reduceMotion = useReducedMotion()
  const [platform] = useState(platformType)
  const [available, setAvailable] = useState(false)
  const [working, setWorking] = useState(false)
  const [instructions, setInstructions] = useState(false)
  const [installed, setInstalled] = useState(false)
  const [copied, setCopied] = useState(false)
  const promptRef = useRef<NativeInstallEvent | null>(null)

  useEffect(() => {
    if (launchedAsApp()) {
      window.location.replace('/')
      return
    }
    let mounted = true
    const availableHandler = (event: Event) => {
      event.preventDefault()
      promptRef.current = event as NativeInstallEvent
      if (mounted) setAvailable(true)
    }
    const installedHandler = () => {
      try { localStorage.setItem('rateapp-install-confirmed', 'yes') } catch { /* Optional storage. */ }
      if (mounted) setInstalled(true)
    }
    window.addEventListener('beforeinstallprompt', availableHandler)
    window.addEventListener('appinstalled', installedHandler)

    const nav = navigator as PwaNavigator
    if (typeof nav.getInstalledRelatedApps === 'function') {
      void nav.getInstalledRelatedApps().then((apps) => {
        if (mounted && apps.some((app) => app.platform === 'webapp')) installedHandler()
      }).catch(() => { /* The browser may not provide this information. */ })
    }
    return () => {
      mounted = false
      window.removeEventListener('beforeinstallprompt', availableHandler)
      window.removeEventListener('appinstalled', installedHandler)
    }
  }, [])

  const startInstall = async () => {
    const event = promptRef.current
    if (!event) {
      setInstructions(true)
      return
    }
    promptRef.current = null
    setAvailable(false)
    setWorking(true)
    try {
      // A Chromium browser allows this only directly after user interaction.
      await event.prompt()
      const result = await event.userChoice
      if (result.outcome === 'accepted') {
        setInstalled(true)
        try { localStorage.setItem('rateapp-install-confirmed', 'yes') } catch { /* Optional. */ }
      } else {
        setInstructions(true)
      }
    } catch {
      setInstructions(true)
    } finally {
      setWorking(false)
    }
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText('https://rateapp-delta.vercel.app/install')
      setCopied(true)
    } catch { setCopied(false) }
  }

  const iosOther = platform === 'ios' && /CriOS|FxiOS|EdgiOS|OPiOS/i.test(navigator.userAgent)
  const instructionsText = platform === 'ios'
    ? iosOther
      ? 'Открой ссылку в Safari, нажми «Поделиться» и выбери «На экран Домой» → «Добавить».'
      : 'Нажми «Поделиться» (квадрат со стрелкой вверх), затем «На экран Домой» → «Добавить».'
    : 'Открой меню браузера ⋮ и выбери «Установить приложение» или «Добавить на главный экран».'

  return (
    <main className="install-page">
      <motion.section
        className="install-page__content"
        initial={reduceMotion ? false : { opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: .45 }}
      >
        <img className="install-page__image" src="/rateapp-loading-gamepad.avif" width={240} height={240} alt="RateApp: неоновый геймпад со звездой и игровыми карточками" />
        <span className="install-page__eyebrow">RateApp для телефона</span>
        <h1>Твои игры всегда рядом</h1>
        <p className="install-page__description">Добавь RateApp на главный экран и открывай игровую библиотеку одним касанием.</p>

        {platform === 'desktop' ? (
          <div className="install-page__steps">
            <h2>Открой на телефоне</h2>
            <p>Перейди по этой же ссылке в браузере iPhone или Android, чтобы установить приложение.</p>
            <button type="button" className="install-page__primary" onClick={() => { void copyLink() }}>
              {copied ? 'Ссылка скопирована' : 'Скопировать ссылку для телефона'}
            </button>
          </div>
        ) : installed ? (
          <div className="install-page__steps" role="status">
            <h2>RateApp уже установлен!</h2>
            <p>Найди приложение на главном экране телефона или открой сайт.</p>
            <a className="install-page__primary" href="/">Открыть RateApp</a>
          </div>
        ) : (
          <>
            <button
              type="button"
              className="install-page__primary"
              disabled={working}
              onClick={() => { void startInstall() }}
            >
              {working ? 'Открываем установку…' : available ? 'Установить RateApp' : platform === 'ios' ? 'Как установить на iPhone' : 'Установить RateApp'}
            </button>
            {instructions && (
              <div className="install-page__steps" role="status">
                <h2>{platform === 'ios' ? 'Установка на iPhone' : 'Установка через браузер'}</h2>
                <p>{instructionsText}</p>
              </div>
            )}
            <p className="install-page__note">
              {platform === 'ios'
                ? 'iOS использует меню «Поделиться» для установки.'
                : available ? 'Нажми кнопку, чтобы открыть системную установку.' : 'Если браузер не предложит установку, покажем инструкцию.'}
            </p>
          </>
        )}
        <a className="install-page__back" href="/">Продолжить в браузере</a>
        <span className="install-page__platforms">iOS · Android</span>
      </motion.section>
    </main>
  )
}
