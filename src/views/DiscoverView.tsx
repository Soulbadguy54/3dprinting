import { useCallback, useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, TouchEvent as ReactTouchEvent } from 'react'
import { AnimatePresence, animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import type { PanInfo } from 'motion/react'
import { Cover } from '../components/GameCard'
import Icon from '../components/Icon'
import type { Game } from '../data'

type DiscoveryAction = 'like' | 'dislike' | 'wishlist'
type Departure = 'left' | 'right' | 'up'
type Details = {
  summary?: string | null
  storyHours?: number | null
  completionHours?: number | null
  storeLinks?: { provider: string; label: string; url: string }[]
  trailerUrl?: string | null
}
type Feed = { items: Game[]; remaining: number }
const HELP_KEY = 'rateapp-discovery-fullscreen-v2'

function getHelpKey(nickname: string) {
  return HELP_KEY + ':' + nickname.toLowerCase()
}

function dateLabel(game: Game) {
  if (!game.releaseDate) return game.year ? String(game.year) : 'Дата выхода неизвестна'
  const value = new Date(game.releaseDate + 'T12:00:00')
  if (Number.isNaN(value.getTime())) return String(game.year || 'Дата выхода неизвестна')
  const date = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(value)
  return date
}

function clamp(value: number) {
  return Math.max(0, Math.min(1, value))
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
  const [helpOpen, setHelpOpen] = useState(() => {
    try { return !localStorage.getItem(getHelpKey(nickname)) }
    catch { return true }
  })
  const [departure, setDeparture] = useState<Departure>('right')

  // One shared spring drives the real drag position, sheet, metadata and backdrop.
  const reveal = useMotionValue(0)
  const [stageHeight, setStageHeight] = useState(650)
  const stageRef = useRef<HTMLDivElement>(null)
  const pullRef = useRef<{ pointerId: number; startY: number; initial: number } | null>(null)
  const sheetAnimationRef = useRef<{ stop: () => void } | null>(null)
  const mountedRef = useRef(true)
  const loadingRef = useRef(false)

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const observer = new ResizeObserver(entries => {
      const measured = entries[0]?.contentRect.height
      if (measured && measured > 0) setStageHeight(measured)
    })
    observer.observe(stage)
    return () => observer.disconnect()
  }, [])

  const sheetHeight = Math.max(300, Math.min(stageHeight * .79, stageHeight - 65))
  const peekHeight = Math.min(225, Math.max(173, stageHeight * .34))
  const travel = Math.max(0, sheetHeight - peekHeight)
  const sheetY = useTransform(reveal, value => travel * (1 - value))
  const detailOpacity = useTransform(reveal, [0, .22, .92], [0, 0, 1])
  const detailOffset = useTransform(reveal, [0, 1], [22, 0])
  const frostOpacity = useTransform(reveal, [0, 1], [.06, .45])

  const settleSheet = (open: boolean) => {
    sheetAnimationRef.current?.stop()
    setExpanded(open)
    sheetAnimationRef.current = animate(reveal, open ? 1 : 0, reducedMotion
      ? { duration: 0 }
      : { type: 'spring', stiffness: 345, damping: 34, mass: .87 })
  }

  const onPullStart = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (busy || helpOpen) return
    event.stopPropagation()
    sheetAnimationRef.current?.stop()
    pullRef.current = { pointerId: event.pointerId, startY: event.clientY, initial: reveal.get() }
    // Captured pointers can be lost when a transformed handle moves in WebKit.
    // Window listeners below also follow the gesture until it ends.
    // Drag is tracked globally; avoid pointer-capture cancellation in Safari.
  }
  const updatePull = (pointerId: number, clientY: number) => {
    const pointer = pullRef.current
    if (!pointer || pointer.pointerId !== pointerId) return
    reveal.set(clamp(pointer.initial + (pointer.startY - clientY) / Math.max(1, travel)))
  }
  const finishPull = (pointerId: number, clientY: number) => {
    const pointer = pullRef.current
    if (!pointer || pointer.pointerId !== pointerId) return
    updatePull(pointerId, clientY)
    pullRef.current = null
    const moved = Math.abs(clientY - pointer.startY)
    if (moved < 7) {
      if (!expanded) void showDetails()
      else settleSheet(false)
      return
    }
    if (reveal.get() >= .48) void showDetails()
    else settleSheet(false)
  }
  const onPullTouchStart = (event: ReactTouchEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (pullRef.current || busy || helpOpen || !event.touches.length) return
    sheetAnimationRef.current?.stop()
    pullRef.current = { pointerId: -2, startY: event.touches[0].clientY, initial: reveal.get() }
  }
  const onPullMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    updatePull(event.pointerId, event.clientY)
  }
  const onPullEnd = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    finishPull(event.pointerId, event.clientY)
  }

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
        return initial ? payload.items : additions.length ? [...previous, ...additions] : previous
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
    return () => {
      mountedRef.current = false
      sheetAnimationRef.current?.stop()
    }
  }, [loadFeed])

  useEffect(() => {
    if (!loading && cards.length - index <= 5 && remaining > cards.length - index && !loadingMore && !error) {
      void loadFeed()
    }
  }, [cards.length, index, loading, loadingMore, remaining, error, loadFeed])

  const game = cards[index]
  const showDetails = async () => {
    if (!game || busy || helpOpen) return
    settleSheet(true)
    if (details[game.id]) return
    setDetailLoading(true)
    try {
      const response = await fetch('/api/games/' + game.id + '/details')
      if (!response.ok) throw new Error('Не удалось загрузить описание.')
      const payload = await response.json() as Details
      if (mountedRef.current) setDetails(current => ({ ...current, [game.id]: payload }))
    } catch {
      if (mountedRef.current) setDetails(current => ({ ...current, [game.id]: { summary: null } }))
    } finally {
      if (mountedRef.current) setDetailLoading(false)
    }
  }

  const decide = async (action: DiscoveryAction) => {
    if (!game || busy || helpOpen || expanded || reveal.get() > .03) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/discover/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gameId: game.id, action }),
      })
      if (!response.ok) throw new Error('Не удалось сохранить свайп. Повтори попытку.')
      setDeparture(action === 'like' ? 'right' : action === 'dislike' ? 'left' : 'up')
      setHistory(previous => [...previous, { gameId: game.id, action }])
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
    if (!last || busy || helpOpen || expanded) return
    setBusy(true)
    try {
      const response = await fetch('/api/discover/feedback/' + last.gameId, { method: 'DELETE' })
      if (!response.ok) throw new Error('Не удалось отменить свайп.')
      setHistory(current => current.slice(0, -1))
      setIndex(value => Math.max(0, value - 1))
      if (last.action === 'wishlist') onWishlistChange()
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка соединения.')
    } finally {
      setBusy(false)
    }
  }

  const onCardDragEnd = (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
    if (busy || helpOpen || expanded || reveal.get() > .03) return
    const { x, y } = info.offset
    if (y < -105 && Math.abs(y) > Math.abs(x) * 1.12) void decide('wishlist')
    else if (Math.abs(x) > 95 && Math.abs(x) > Math.abs(y) * 1.07) {
      void decide(x > 0 ? 'like' : 'dislike')
    }
  }

  useEffect(() => {
    // WebKit/iOS may stop delivering events to a handle that moves under the
    // pointer. Receive the same gesture on window, even outside the handle.
    const move = (event: PointerEvent) => {
      if (pullRef.current?.pointerId !== event.pointerId) return
      if (event.cancelable) event.preventDefault()
      updatePull(event.pointerId, event.clientY)
    }
    const up = (event: PointerEvent) => finishPull(event.pointerId, event.clientY)
    const cancel = (event: PointerEvent) => {
      if (pullRef.current?.pointerId !== event.pointerId) return
      pullRef.current = null
      settleSheet(expanded)
    }
    // Safari and Playwright's emulated mouse/touch events may lose a pointer
    // event when the panel itself moves. Use the last reported position.
    const mouseMove = (event: MouseEvent) => {
      if (pullRef.current) updatePull(pullRef.current.pointerId, event.clientY)
    }
    const mouseUp = (event: MouseEvent) => {
      if (pullRef.current) finishPull(pullRef.current.pointerId, event.clientY)
    }
    const touchMove = (event: TouchEvent) => {
      if (!pullRef.current || !event.touches.length) return
      if (event.cancelable) event.preventDefault()
      updatePull(pullRef.current.pointerId, event.touches[0].clientY)
    }
    const touchEnd = (event: TouchEvent) => {
      if (pullRef.current && event.changedTouches.length)
        finishPull(pullRef.current.pointerId, event.changedTouches[0].clientY)
    }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', cancel)
    window.addEventListener('mousemove', mouseMove)
    window.addEventListener('mouseup', mouseUp)
    window.addEventListener('touchmove', touchMove, { passive: false })
    window.addEventListener('touchend', touchEnd)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', cancel)
      window.removeEventListener('mousemove', mouseMove)
      window.removeEventListener('mouseup', mouseUp)
      window.removeEventListener('touchmove', touchMove)
      window.removeEventListener('touchend', touchEnd)
    }
  })

  const dismissHelp = () => {
    setHelpOpen(false)
    try { localStorage.setItem(getHelpKey(nickname), '1') } catch { /* Private browsing */ }
  }
  const currentDetails = game ? details[game.id] : undefined

  return (
    <section className="discover-screen" aria-label="Персональные рекомендации игр">
      <header className="discover-topbar">
        <button type="button" className="discover-icon-button"
          aria-label="Вернуться в базу игр" onClick={onExit}>
          <Icon name="back" size={23} />
        </button>
        {history.length > 0 && !expanded && (
          <button type="button" className="discover-icon-button discover-icon-button--undo"
            aria-label="Шаг назад" disabled={busy || helpOpen} onClick={() => void undo()}>↶</button>
        )}
        <button type="button" className="discover-icon-button discover-icon-button--info"
          aria-label="Показать обучение" onClick={() => setHelpOpen(true)}>i</button>
      </header>

      <div ref={stageRef} className="discover-stage" aria-live="polite">
        {loading ? (
          <div className="discover-state" role="status"><span className="discover-loader" />Подбираем игры…</div>
        ) : !game ? (
          <div className="discover-state">
            <span className="discover-state__icon">✦</span>
            <h2>Пока всё просмотрено</h2>
            <p>Мы запомним твой вкус. Новые варианты появятся по мере пополнения каталога.</p>
            <button type="button" onClick={() => { setCards([]); setIndex(0); void loadFeed(true) }}>Обновить ленту</button>
          </div>
        ) : (
          <AnimatePresence mode="wait" initial={false} custom={departure}>
            <motion.div
              key={game.id}
              className="discover-card"
              aria-label={'Рекомендована игра ' + game.title}
              initial={reducedMotion ? false : { opacity: 0, scale: .975 }}
              animate={{ opacity: 1, scale: 1, x: 0, y: 0, rotate: 0 }}
              variants={{
                departure: (direction: Departure) => reducedMotion
                  ? { opacity: 0 }
                  : direction === 'right'
                    ? { x: 440, rotate: 13, opacity: 0 }
                    : direction === 'left'
                      ? { x: -440, rotate: -13, opacity: 0 }
                      : { y: -530, scale: .9, opacity: 0 },
              }}
              exit="departure"
              transition={{ type: 'spring', stiffness: 305, damping: 30 }}
              drag={!busy && !helpOpen && !expanded}
              dragConstraints={{ left: -150, right: 150, top: -150, bottom: 95 }}
              dragElastic={.5}
              dragSnapToOrigin
              dragMomentum={false}
              onDragEnd={onCardDragEnd}
              style={{ touchAction: 'none' }}
            >
              <div className="discover-cover" aria-hidden="true">
                <Cover game={game} priority />
                <div className="discover-cover__fade" />
              </div>

              {!expanded && !helpOpen && (
                <div className="discover-hints" aria-hidden="true">
                  <span className="discover-hint discover-hint--up">↑ <b>Хочу поиграть</b></span>
                  <span className="discover-hint discover-hint--left">← <b>Не нравится</b></span>
                  <span className="discover-hint discover-hint--right"><b>Нравится</b> →</span>
                </div>
              )}

              <motion.div className="discover-sheet-backdrop" style={{ opacity: frostOpacity }} aria-hidden="true" />
              <motion.div className={expanded ? 'discover-sheet discover-sheet--expanded' : 'discover-sheet'}
                style={{ height: sheetHeight, y: sheetY }}
                onPointerDown={event => event.stopPropagation()}>
                <button
                  className="discover-sheet__handle"
                  type="button"
                  aria-label={expanded ? 'Свернуть подробности' : 'Развернуть подробности'}
                  aria-expanded={expanded}
                  onPointerDown={onPullStart}
                  onTouchStart={onPullTouchStart}
                  onPointerMove={onPullMove}
                  onPointerUp={onPullEnd}
                  onPointerCancel={(event) => {
                    if (pullRef.current?.pointerId === event.pointerId) {
                      pullRef.current = null
                      settleSheet(expanded)
                    }
                  }}
                >
                  <span className={expanded ? 'discover-sheet__chevron discover-sheet__chevron--down' : 'discover-sheet__chevron'} />
                </button>

                <motion.div className="discover-sheet__body">
                  <div className="discover-sheet__summary-row">
                    <motion.div className="discover-sheet__identity" layout transition={{ type: 'spring', stiffness: 300, damping: 28 }}>
                      <h2>{game.title}</h2>
                      <p>{dateLabel(game)}</p>
                      <p>{game.genres.slice(0, 3).join(' · ') || 'Жанр не указан'}</p>
                    </motion.div>
                    <motion.div className="discover-sheet__ratings" layout
                      aria-label="Рейтинги игры" transition={{ type: 'spring', stiffness: 300, damping: 28 }}>
                      <span className="discover-rating discover-rating--igdb">
                        <small>IGDB</small> <strong>{game.igdbRating || '—'}</strong>
                      </span>
                      <span className="discover-rating discover-rating--rateapp">
                        <small>Rate APP</small> <strong>{game.communityRating || '—'}</strong>
                      </span>
                    </motion.div>
                  </div>
                  <motion.div className="discover-sheet__extra"
                    style={{ opacity: detailOpacity, y: detailOffset, pointerEvents: expanded ? 'auto' : 'none' }}
                    aria-hidden={!expanded}>
                    <p className="discover-sheet__platforms">{game.platforms.slice(0, 4).join(' · ')}</p>
                    <p className="discover-sheet__description">
                      {detailLoading ? 'Загружаем описание…'
                        : currentDetails?.summary || 'Описание пока недоступно. Посмотри трейлер или страницу игры в магазине.'}
                    </p>
                    {(currentDetails?.storeLinks?.length || currentDetails?.trailerUrl) ? (
                      <div className="discover-sheet__links">
                        {currentDetails?.storeLinks?.map(link => (
                          <a key={link.provider} href={link.url} target="_blank" rel="noopener noreferrer">
                            <span>{link.label}</span><span aria-hidden="true">↗</span>
                          </a>
                        ))}
                        {currentDetails.trailerUrl && (
                          <a href={currentDetails.trailerUrl} target="_blank" rel="noopener noreferrer">
                            <span>▶ Трейлер</span><span aria-hidden="true">↗</span>
                          </a>
                        )}
                      </div>
                    ) : null}
                  </motion.div>
                </motion.div>
              </motion.div>
            </motion.div>
          </AnimatePresence>
        )}
        {error && <div className="discover-error" role="alert">{error}</div>}
      </div>

      <AnimatePresence>
        {helpOpen && (
          <motion.button
            className="discover-help"
            type="button"
            aria-label="Закрыть обучение"
            initial={reducedMotion ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={dismissHelp}>
            <span className="discover-help__panel">
              <span className="discover-help__label">DISCOVER · RATE APP</span>
              <strong>Новые игры для тебя</strong>
              <span className="discover-help__description">Подбираем игры по твоим оценкам. Управляй карточкой жестами:</span>
              <span className="discover-help__gesture-map">
                <span className="discover-help__gesture discover-help__gesture--up">↑ <b>Хочу поиграть</b></span>
                <span className="discover-help__gesture discover-help__gesture--left">← <b>Не нравится</b></span>
                <span className="discover-help__gesture discover-help__gesture--right"><b>Нравится</b> →</span>
              </span>
              <span className="discover-help__details">⌃ Потяни шеврон вверх — подробности. Вниз — свернуть.</span>
              <span className="discover-help__continue">Понятно</span>
              <span className="discover-help__later">Подсказку можно открыть снова через i</span>
            </span>
          </motion.button>
        )}
      </AnimatePresence>
    </section>
  )
}
