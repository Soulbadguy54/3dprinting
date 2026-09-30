import { useState } from 'react'
import './auth.css'

export type AuthUser = {
  id: number
  email: string
  nickname: string
  createdAt: string
  public: boolean
}

type Mode = 'login' | 'register'

export default function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated: (user: AuthUser) => void
}) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [nickname, setNickname] = useState('')
  const [identifier, setIdentifier] = useState('')
  const [pin, setPin] = useState('')
  const [pinConfirm, setPinConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const switchMode = (next: Mode) => {
    setMode(next)
    setError('')
    setPin('')
    setPinConfirm('')
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')

    if (mode === 'register' && pin !== pinConfirm) {
      setError('PIN-коды не совпадают.')
      return
    }

    setBusy(true)
    try {
      const response = await fetch(
        mode === 'register' ? '/api/auth/register' : '/api/auth/login',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            mode === 'register'
              ? { email, nickname, pin }
              : { identifier, pin },
          ),
        },
      )

      const data = await response.json().catch(() => null) as
        | AuthUser
        | { detail?: string }
        | null

      if (!response.ok) {
        setError(data && 'detail' in data && data.detail ? data.detail : 'Не удалось войти.')
        return
      }

      onAuthenticated(data as AuthUser)
    } catch {
      setError('Не удалось связаться с сервером. Попробуйте ещё раз.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand">
          <span className="auth-brand__mark">R</span>
          <div>
            <strong>RateApp</strong>
            <span>твоя игровая библиотека</span>
          </div>
        </div>

        <div className="auth-copy">
          <span>{mode === 'login' ? 'С возвращением' : 'Новый профиль'}</span>
          <h1>{mode === 'login' ? 'Войти' : 'Создать аккаунт'}</h1>
          <p>
            {mode === 'login'
              ? 'Используй email или ник и свой PIN.'
              : 'Профиль и игровые коллекции будут публичными. Email останется приватным.'}
          </p>
        </div>

        <div className="auth-tabs">
          <button
            className={mode === 'login' ? 'auth-tab auth-tab--active' : 'auth-tab'}
            onClick={() => switchMode('login')}
            type="button"
          >
            Вход
          </button>
          <button
            className={mode === 'register' ? 'auth-tab auth-tab--active' : 'auth-tab'}
            onClick={() => switchMode('register')}
            type="button"
          >
            Регистрация
          </button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          {mode === 'register' ? (
            <>
              <label>
                <span>Email</span>
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  required
                />
              </label>
              <label>
                <span>Никнейм</span>
                <input
                  type="text"
                  autoComplete="username"
                  value={nickname}
                  onChange={(event) => setNickname(event.target.value.toLowerCase())}
                  placeholder="nickname"
                  pattern="[a-z0-9_]{3,24}"
                  required
                />
                <small>3–24 символа: латиница, цифры и _</small>
              </label>
            </>
          ) : (
            <label>
              <span>Email или ник</span>
              <input
                type="text"
                autoComplete="username"
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                placeholder="you@example.com или nickname"
                required
              />
            </label>
          )}

          <label>
            <span>PIN-код</span>
            <input
              type="password"
              inputMode="numeric"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={pin}
              onChange={(event) => setPin(event.target.value.replace(/\D/g, '').slice(0, 8))}
              placeholder="••••••"
              minLength={4}
              maxLength={8}
              required
            />
            <small>4–8 цифр. На этом устройстве повторно вводить PIN обычно не понадобится.</small>
          </label>

          {mode === 'register' && (
            <label>
              <span>Повтори PIN</span>
              <input
                type="password"
                inputMode="numeric"
                autoComplete="new-password"
                value={pinConfirm}
                onChange={(event) => setPinConfirm(event.target.value.replace(/\D/g, '').slice(0, 8))}
                placeholder="••••••"
                minLength={4}
                maxLength={8}
                required
              />
            </label>
          )}

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-submit" disabled={busy}>
            {busy
              ? 'Подождите…'
              : mode === 'login'
                ? 'Войти'
                : 'Создать аккаунт'}
          </button>
        </form>

        <p className="auth-security">
          PIN хранится только в виде защищённого хэша. После входа браузер получает защищённую сессию.
        </p>
      </section>
    </main>
  )
}
