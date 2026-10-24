import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { PanInfo } from 'motion/react'
import { Cover } from '../components/GameCard'
import Icon from '../components/Icon'
import type { Game } from '../data'
import './DiscoverView.css'

type DiscoveryAction = 'like' | 'dislike' | 'wishlist'
type Details = {
  summary?: string | null
  storyHours?: number | null
  completionHours?: number | null
  storeLinks?: { provider: string; label: string; url: string }[]
  trailerUrl?: string | null
}
type Feed = { items: Game[]; remaining: number }
const HELP_KEY = 'rateapp-discovery-help-v1'
const LESSONS = [
  { icon: '✦', title: 'Твои новые игры', text: 'Листай карточки — мы подбираем игры, похожие на те, что ты высоко оценил.' },
  { icon: '←', title: 'Влево — нравится', text: 'Запомним интерес к игре. Это не добавляет её в список желаемого.' },
  { icon: '→', title: 'Вправо — не нравится', text: 'Покажем меньше похожих игр. Решение можно отменить.' },
  { icon: '↑', title: 'Вверх — хочу пройти', text: 'Добавим игру в твою коллекцию ❤️ «Хочу пройти».' },
  { icon: '↓', title: 'Вниз — подробности', text: 'Обложка уменьшится и откроются описание, подробности и ссылки.' },
]

function getHelpKey(nickname: string) {
  return `${HELP_KEY}:${nickname.toLowerCase()}`
}

export default function DiscoverView({
  nickname, onExit, onWishlistChange,
}: {
  nickname: string
  onExit: () => void
  onWishlistChange: () => void
}) {
  const reducedMotion = useReducedMotion()
  const [cards, setCards] = useState<Game[]>([])
  const [index, setIndex] = useState(0)
  const [history, setHistory] = useState<{ gameId: number; action: DiscoveryAction }[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [remaining, setRemaining] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [details, setDetails] = useState<Record<number, Details>>({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [helpStep, setHelpStep] = useState<number | null>(() => {
    try { return localStorage.getItem(getHelpKey(nickname)) ? null : 0 }
    catch { return 0 }
  })
  const [departure, setDeparture] = useState<'left' | 'right' | 'up'>('left')
  const mountedRef = useRef(true)
  const loadingRef = useRef(false)

  const loadFeed = useCallback(async (initial = false) => {
    if (loadingRef.current) return
    loadingRef.current = true
    if (initial) setLoading(true)
    else setLoadingMore(true)
    try {
      const response = await fetch('/api/discover/feed', { credentials: 'same-origin' })
      if (!response.ok) throw new Error('Не удалось загрузить рекомендации.')
      const payload = await response.json() as Feed
      if (!mountedRef.current) return
      setRemaining(payload.remaining)
      setCards(previous => {
        const found = new Set(previous.map(item => item.id))
        const additions = payload.items.filter(item => !found.has(item.id))
        return initial ? payload.items : [...previous, ...additions]
      })
      setError('')
    } catch (reason) {
      if (mountedRef.current) setError(reason instanceof Error ? reason.message : 'Ошибка соединения.')
    } finally {
      loadingRef.current = false
      if (mountedRef.current) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void loadFeed(true)
    return () => { mountedRef.current = false }
  }, [loadFeed])

  useEffect(() => {
    if (!loading && cards.length - index <= 5 && remaining > cards.length - index && !loadingMore && !error) {
      void loadFeed()
    }
  }, [cards.length, index, loading, loadingMore, remaining, error, loadFeed])

  const game = cards[index]

  const showDetails = async () => {
    if (!game || busy) return
    setExpanded(true)
    if (details[game.id]) return
    setDetailLoading(true)
    try {
      const response = await fetch(`/api/games/${game.id}/details`)
      if (!response.ok) throw new Error('Не удалось загрузить информацию.')
      const payload = await response.json() as Details
      setDetails(current => ({ ...current, [game.id]: payload }))
    } catch {
      setDetails(current => ({ ...current, [game.id]: { summary: null } }))
    } finally {
      setDetailLoading(false)
    }
  }

  const decide = async (action: DiscoveryAction) => {
    if (!game || busy || helpStep !== null) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/discover/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gameId: game.id, action }),
      })
      if (!response.ok) throw new Error('Не удалось сохранить свайп. Повтори попытку.')
      setDeparture(action === 'like' ? 'left' : action === 'dislike' ? 'right' : 'up')
      setHistory(previous => [...previous, { gameId: game.id, action }])
      setExpanded(false)
      setIndex(value => value + 1)
      if (action === 'wishlist') onWishlistChange()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка соединения.')
    } finally {
      setBusy(false)
    }
  }

  const undo = async () => {
    const last = history[history.length - 1]
    if (!last || busy || helpStep !== null) return
    setBusy(true)
    try {
      const response = await fetch(`/api/discover/feedback/${last.gameId}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('Не удалось отменить свайп.')
      setHistory(current => current.slice(0, -1))
      setIndex(value => Math.max(0, value - 1))
      setExpanded(false)
      if (last.action === 'wishlist') onWishlistChange()
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка соединения.')
    } finally {
      setBusy(false)
    }
  }

  const onDragEnd = (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
    if (busy || helpStep !== null) return
    const { x, y } = info.offset
    if (Math.abs(y) > 95 && Math.abs(y) > Math.abs(x) * 1.15) {
      if (y > 0) void showDetails()
      else void decide('wishlist')
    } else if (Math.abs(x) > 95) {
      void decide(x < 0 ? 'like' : 'dislike')
    }
  }

  const nextHelp = () => {
    if (helpStep === null) return
    if (helpStep < LESSONS.length - 1) setHelpStep(helpStep + 1)
    else {
      setHelpStep(null)
      try { localStorage.setItem(getHelpKey(nickname), '1') } catch { /* Private browsing */ }
    }
  }

  const currentDetails = game ? details[game.id] : undefined

  return (
    <div className="discover-screen">
      <header className="discover-topbar">
        <button className="discover-icon-button" type="button" aria-label="Вернуться в базу игр" onClick={onExit}><Icon name="back" size={21} /></button>
        <div className="discover-topbar__text">
          <span>DISCOVER</span>
          <strong>Для тебя</strong>
        </div>
        <button className="discover-icon-button discover-icon-button--info" type="button" aria-label="Показать обучение" onClick={() => setHelpStep(0)}>i</button>
      </header>

      <div className="discover-stage" aria-live="polite">
        {loading ? (
          <div className="discover-state" role="status"><span className="discover-loader" />Подбираем игры…</div>
        ) : !game ? (
          <div className="discover-state">
            <span className="discover-state__icon">✦</span>
            <h2>Пока всё просмотрено</h2>
            <p>Мы запомним твой вкус. Новые варианты появятся по мере пополнения каталога.</p>
            <button onClick={() => { setCards([]); setIndex(0); void loadFeed(true) }}>Обновить ленту</button>
          </div>
        ) : (
          <AnimatePresence mode="wait" initial={false} custom={departure}>
            <motion.div
              key={game.id}
              className={expanded ? 'discover-card discover-card--expanded' : 'discover-card'}
              initial={reducedMotion ? false : { opacity: 0, scale: .96, y: 18 }}
              animate={{ opacity: 1, scale: 1, x: 0, y: 0, rotate: 0 }}
              exit={reducedMotion ? { opacity: 0 } : departure === 'left'
                ? { x: -380, rotate: -16, opacity: 0 }
                : departure === 'right'
                  ? { x: 380, rotate: 16, opacity: 0 }
                  : { y: -480, scale: .86, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 290, damping: 27 }}
              drag={helpStep === null && !busy && !expanded ? true : false}
              dragConstraints={{ left: -145, right: 145, top: -140, bottom: 130 }}
              dragSnapToOrigin
              dragMomentum={false}
              onDragEnd={onDragEnd}
              style={{ touchAction: expanded ? 'pan-y' : 'none' }}
              aria-label={`Рекомендована игра ${game.title}`}
            >
              <motion.div className="discover-card__layout" layout transition={{ type: 'spring', stiffness: 330, damping: 30 }}>
                <motion.div className="discover-card__cover" layout transition={{ type: 'spring', stiffness: 330, damping: 30 }}>
                  <Cover game={game} priority />
                  {!expanded && <div className="discover-card__cover-fade" />}
                </motion.div>
                <motion.div className="discover-card__intro" layout>
                  <span className="discover-card__eyebrow">{expanded ? 'ОБ ИГРЕ' : 'ВОЗМОЖНО, ТВОЁ'}</span>
                  <h2>{game.title}</h2>
                  <p>{game.year || 'Дата неизвестна'} · {game.genres.slice(0, 2).join(' / ') || 'Жанр неизвестен'}</p>
                  {expanded && <span className="discover-card__developer">{game.developer !== '—' ? game.developer : 'Разработчик не указан'}</span>}
                </motion.div>
              </motion.div>

              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div className="discover-card__details"
                    initial={reducedMotion ? false : { opacity: 0, height: 0, y: 20 }}
                    animate={{ opacity: 1, height: 'auto', y: 0 }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: .33, ease: [0.2, 1, 0.3, 1] }}>
                    <div className="discover-card__stats">
                      <span><b>{game.igdbRating || '—'}</b><small>IGDB / 100</small></span>
                      <span><b>{game.communityRating || '—'}</b><small>Rate APP / 10</small></span>
                      <span><b>{game.platforms.slice(0, 2).join(', ') || '—'}</b><small>Платформы</small></span>
                    </div>
                    <h3>Описание</h3>
                    <p className="discover-card__summary">{detailLoading ? 'Загружаем описание…' : currentDetails?.summary || 'Описание пока недоступно. Можно посмотреть трейлер или магазин игры.'}</p>
                    {!!currentDetails?.storeLinks?.length && (
                      <div className="discover-card__links">
                        {currentDetails.storeLinks.map(link => (
                          <a key={link.provider} href={link.url} target="_blank" rel="noopener noreferrer">{link.label} ↗</a>
                        ))}
                      </div>
                    )}
                    {!!currentDetails?.trailerUrl && <a className="discover-card__trailer" href={currentDetails.trailerUrl} target="_blank" rel="noopener noreferrer">▶ Смотреть трейлер</a>}
                    <button className="discover-card__collapse" type="button" onPointerDown={event => event.stopPropagation()} onClick={() => setExpanded(false)}>Свернуть подробности ↑</button>
                  </motion.div>
                )}
              </AnimatePresence>

              {!expanded && (
                <button type="button" className="discover-card__expand" onPointerDown={event => event.stopPropagation()} onClick={() => { void showDetails() }}>
                  <span>↓</span> Свайп вниз — подробнее
                </button>
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </div>

      <div className="discover-actions" aria-label="Действия с рекомендацией">
        <button type="button" className="discover-actions__choice discover-actions__choice--like" disabled={!game || busy || helpStep !== null} onClick={() => void decide('like')} aria-label="Нравится, следующая игра">← <span>Нравится</span></button>
        <button type="button" className="discover-actions__choice discover-actions__choice--wishlist" disabled={!game || busy || helpStep !== null} onClick={() => void decide('wishlist')} aria-label="Добавить в Хочу пройти">↑ <span>Хочу</span></button>
        <button type="button" className="discover-actions__choice discover-actions__choice--dislike" disabled={!game || busy || helpStep !== null} onClick={() => void decide('dislike')} aria-label="Не нравится, следующая игра">→ <span>Не моё</span></button>
      </div>
      <div className="discover-footnote">
        <button type="button" disabled={!history.length || busy || helpStep !== null} onClick={() => void undo()}><span>↶</span> Шаг назад</button>
        <span>{game ? `${index + 1} · ${remaining} в подборке` : loadingMore ? 'Ещё ищем…' : ' '}</span>
      </div>
      {error && <p className="discover-error" role="alert">{error}</p>}

      <AnimatePresence>
        {helpStep !== null && (
          <motion.button
            type="button"
            className="discover-help"
            aria-label="Следующий шаг обучения"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={nextHelp}
          >
            <span className="discover-help__glow" />
            <span className="discover-help__panel">
              <span className="discover-help__counter">{String(helpStep + 1).padStart(2, '0')} / {String(LESSONS.length).padStart(2, '0')}</span>
              <span className="discover-help__icon">{LESSONS[helpStep].icon}</span>
              <strong>{LESSONS[helpStep].title}</strong>
              <span className="discover-help__copy">{LESSONS[helpStep].text}</span>
              <span className="discover-help__continue">{helpStep === LESSONS.length - 1 ? 'Нажми, чтобы начать' : 'Коснись экрана, чтобы продолжить'} →</span>
              <span className="discover-help__dots">{LESSONS.map((_, i) => <i key={i} className={i === helpStep ? 'active' : ''} />)}</span>
            </span>
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  )
}
