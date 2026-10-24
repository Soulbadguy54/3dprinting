import { useCallback, useEffect, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, TouchEvent as ReactTouchEvent } from 'react'
import { AnimatePresence, animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import type { PanInfo } from 'motion/react'
import { Cover } from '../components/GameCard'
import Icon from '../components/Icon'
import type { Game } from '../data'

type DiscoveryAction = 'like' | 'dislike' | 'wishlist'
type Direction = 'left' | 'right' | 'up'
type Details = {
  summary?: string | null
  storeLinks?: { provider: string; label: string; url: string }[]
  trailerUrl?: string | null
}
type Feed = { items: Game[]; remaining: number }
type Pull = { pointerId: number; startY: number; startReveal: number }

const HELP_KEY = 'rateapp-discovery-integrated-v3'
const getHelpKey = (nickname: string) => HELP_KEY + ':' + nickname.toLowerCase()
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n))

function releaseLabel(game: Game) {
  if (!game.releaseDate) return game.year ? String(game.year) : 'Дата неизвестна'
  const date = new Date(game.releaseDate + 'T12:00:00')
  return Number.isNaN(date.getTime())
    ? String(game.year || 'Дата неизвестна')
    : new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(date)
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
  const [remaining, setRemaining] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [details, setDetails] = useState<Record<number, Details>>({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [departure, setDeparture] = useState<Direction>('right')
  const [helpOpen, setHelpOpen] = useState(() => {
    try { return !localStorage.getItem(getHelpKey(nickname)) } catch { return true }
  })
  const [artworkReady, setArtworkReady] = useState(false)

  const stageRef = useRef<HTMLDivElement>(null)
  const [stageHeight, setStageHeight] = useState(550)
  const mountedRef = useRef(true)
  const loadingRef = useRef(false)
  const pullRef = useRef<Pull | null>(null)
  const sheetAnimationRef = useRef<{ stop: () => void } | null>(null)
  const reveal = useMotionValue(0)
  const cardShift = useMotionValue(0)
  const cardTilt = useMotionValue(0)

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const observer = new ResizeObserver(entries => {
      const height = entries[0]?.contentRect.height
      if (height && height > 0) setStageHeight(height)
    })
    observer.observe(stage)
    return () => observer.disconnect()
  }, [])

  // Only a short strip of the sheet is visible before the chevron is pulled.
  const fullSheetHeight = Math.max(200, Math.min(stageHeight * .78, stageHeight - 16))
  const peekHeight = Math.min(149, Math.max(125, stageHeight * .25))
  const travel = Math.max(1, fullSheetHeight - peekHeight)
  const sheetY = useTransform(reveal, n => travel * (1 - n))
  const detailOpacity = useTransform(reveal, [0, .32, .98], [0, 0, 1])
  const detailRise = useTransform(reveal, [0, 1], [16, 0])

  const settleSheet = (open: boolean) => {
    sheetAnimationRef.current?.stop()
    setExpanded(open)
    sheetAnimationRef.current = animate(reveal, open ? 1 : 0, reducedMotion
      ? { duration: 0 }
      : { duration: .38, ease: [0.22, 1, 0.36, 1] })
  }

  const startPull = (id: number, y: number) => {
    if (busy || helpOpen || pullRef.current) return
    sheetAnimationRef.current?.stop()
    pullRef.current = { pointerId: id, startY: y, startReveal: reveal.get() }
  }
  const movePull = (id: number, y: number) => {
    const pull = pullRef.current
    if (!pull || pull.pointerId !== id) return
    // Dead zone and gentle resistance prevent jerky half-screen pulls.
    const difference = pull.startY - y
    const useful = Math.sign(difference) * Math.max(0, Math.abs(difference) - 18)
    reveal.set(clamp(pull.startReveal + useful / (travel * 1.13), 0, 1))
  }
  const finishPull = (id: number, y: number) => {
    const pull = pullRef.current
    if (!pull || pull.pointerId !== id) return
    movePull(id, y)
    pullRef.current = null
    if (Math.abs(y - pull.startY) < 9) {
      if (expanded) settleSheet(false)
      else void showDetails()
      return
    }
    if (reveal.get() >= .46) void showDetails()
    else settleSheet(false)
  }
  const onPointerStart = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    startPull(event.pointerId, event.clientY)
  }
  const onMouseStart = (event: ReactMouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    startPull(-1, event.clientY)
  }
  const onTouchStart = (event: ReactTouchEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    if (event.touches.length) startPull(-2, event.touches[0].clientY)
  }

  useEffect(() => {
    // A moving transformed handle may lose capture on WebKit. Observe the same
    // pull on window until it is released, including mouse and native touch.
    const pointerMove = (event: PointerEvent) => {
      if (pullRef.current?.pointerId !== event.pointerId) return
      if (event.cancelable) event.preventDefault()
      movePull(event.pointerId, event.clientY)
    }
    const pointerUp = (event: PointerEvent) => finishPull(event.pointerId, event.clientY)
    const mouseMove = (event: MouseEvent) => {
      if (pullRef.current) movePull(pullRef.current.pointerId, event.clientY)
    }
    const mouseUp = (event: MouseEvent) => {
      if (pullRef.current) finishPull(pullRef.current.pointerId, event.clientY)
    }
    const touchMove = (event: TouchEvent) => {
      if (!pullRef.current || !event.touches.length) return
      if (event.cancelable) event.preventDefault()
      movePull(pullRef.current.pointerId, event.touches[0].clientY)
    }
    const touchEnd = (event: TouchEvent) => {
      if (pullRef.current && event.changedTouches.length)
        finishPull(pullRef.current.pointerId, event.changedTouches[0].clientY)
    }
    const pointerCancel = (event: PointerEvent) => {
      if (pullRef.current?.pointerId !== event.pointerId) return
      pullRef.current = null
      settleSheet(expanded)
    }
    window.addEventListener('pointermove', pointerMove, { passive: false })
    window.addEventListener('pointerup', pointerUp)
    window.addEventListener('pointercancel', pointerCancel)
    window.addEventListener('mousemove', mouseMove)
    window.addEventListener('mouseup', mouseUp)
    window.addEventListener('touchmove', touchMove, { passive: false })
    window.addEventListener('touchend', touchEnd)
    return () => {
      window.removeEventListener('pointermove', pointerMove)
      window.removeEventListener('pointerup', pointerUp)
      window.removeEventListener('pointercancel', pointerCancel)
      window.removeEventListener('mousemove', mouseMove)
      window.removeEventListener('mouseup', mouseUp)
      window.removeEventListener('touchmove', touchMove)
      window.removeEventListener('touchend', touchEnd)
    }
  })

  const loadFeed = useCallback(async (initial = false) => {
    if (loadingRef.current) return
    loadingRef.current = true
    if (initial) setLoading(true)
    else setLoadingMore(true)
    try {
      const response = await fetch('/api/discover/feed', { credentials: 'same-origin' })
      if (!response.ok) throw new Error('Не удалось загрузить рекомендации.')
      const data = await response.json() as Feed
      if (!mountedRef.current) return
      setRemaining(data.remaining)
      setCards(previous => {
        const seen = new Set(previous.map(item => item.id))
        const added = data.items.filter(item => !seen.has(item.id))
        return initial ? data.items : [...previous, ...added]
      })
      setError('')
    } catch (reason) {
      if (mountedRef.current) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить игры.')
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

  const game = cards[index]
  useEffect(() => {
    if (!game) return
    setArtworkReady(false)
    // Allow the underlying card to paint before the first-use glass tutorial.
    const timeout = window.setTimeout(() => setArtworkReady(true), 520)
    return () => window.clearTimeout(timeout)
  }, [game?.id])

  useEffect(() => {
    if (!loading && cards.length - index <= 5 && remaining > cards.length - index && !loadingMore && !error) {
      void loadFeed()
    }
  }, [cards.length, index, remaining, loading, loadingMore, error, loadFeed])

  const showDetails = async () => {
    if (!game || busy || helpOpen) return
    settleSheet(true)
    if (details[game.id]) return
    setDetailLoading(true)
    try {
      const response = await fetch('/api/games/' + game.id + '/details')
      if (!response.ok) throw new Error('Ошибка загрузки')
      const payload = await response.json() as Details
      if (mountedRef.current) setDetails(current => ({ ...current, [game.id]: payload }))
    } catch {
      if (mountedRef.current) setDetails(current => ({ ...current, [game.id]: { summary: null } }))
    } finally {
      if (mountedRef.current) setDetailLoading(false)
    }
  }

  const resetTilt = () => {
    animate(cardShift, 0, reducedMotion ? { duration: 0 } : { duration: .22, ease: 'easeOut' })
    animate(cardTilt, 0, reducedMotion ? { duration: 0 } : { duration: .22, ease: 'easeOut' })
  }
  const decide = async (action: DiscoveryAction) => {
    if (!game || busy || helpOpen || expanded || pullRef.current || reveal.get() > .03) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/discover/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gameId: game.id, action }),
      })
      if (!response.ok) throw new Error('Не получилось сохранить свайп — попробуй ещё раз.')
      setDeparture(action === 'like' ? 'right' : action === 'dislike' ? 'left' : 'up')
      setHistory(previous => [...previous, { gameId: game.id, action }])
      setIndex(value => value + 1)
      if (action === 'wishlist') onWishlistChange()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка соединения.')
    } finally {
      resetTilt()
      setBusy(false)
    }
  }

  const undo = async () => {
    const last = history[history.length - 1]
    if (!last || busy || expanded || helpOpen) return
    setBusy(true)
    try {
      const response = await fetch('/api/discover/feedback/' + last.gameId, { method: 'DELETE' })
      if (!response.ok) throw new Error('Не получилось отменить свайп.')
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

  const onPosterPan = (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
    if (busy || expanded || helpOpen || pullRef.current) return
    const { x, y } = info.offset
    if (Math.abs(x) > Math.abs(y) * 1.15) {
      cardShift.set(clamp(x * .1, -13, 13))
      cardTilt.set(clamp(x * .016, -2.3, 2.3))
    }
  }
  const onPosterPanEnd = (_event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
    resetTilt()
    if (busy || expanded || helpOpen || pullRef.current || reveal.get() > .03) return
    const { x, y } = info.offset
    if (y < -120 && Math.abs(y) > Math.abs(x) * 1.16) void decide('wishlist')
    else if (Math.abs(x) > 115 && Math.abs(x) > Math.abs(y) * 1.12) {
      void decide(x > 0 ? 'like' : 'dislike')
    }
  }

  const dismissHelp = () => {
    setHelpOpen(false)
    try { localStorage.setItem(getHelpKey(nickname), '1') } catch { /* Storage blocked */ }
  }
  const currentDetails = game ? details[game.id] : undefined

  return (
    <section className="discover-screen" aria-label="Персональные рекомендации игр">
      <header className="discover-topbar">
        <button type="button" className="discover-icon-button" aria-label="Вернуться в базу игр" onClick={onExit}>
          <Icon name="back" size={22} />
        </button>
        {history.length > 0 && !expanded && (
          <button type="button" className="discover-icon-button discover-icon-button--undo"
            aria-label="Шаг назад" onClick={() => void undo()} disabled={busy || helpOpen}>↶</button>
        )}
        <button type="button" className="discover-icon-button discover-icon-button--info"
          aria-label="Показать обучение" onClick={() => setHelpOpen(true)}>i</button>
      </header>

      <div className="discover-stage" ref={stageRef} aria-live="polite">
        {loading ? (
          <div className="discover-state" role="status"><span className="discover-loader" />Подбираем игры…</div>
        ) : !game ? (
          <div className="discover-state">
            <span className="discover-state__icon">✦</span>
            <h2>Пока всё просмотрено</h2>
            <p>Новые варианты появятся, когда каталог пополнится.</p>
            <button type="button" onClick={() => { setCards([]); setIndex(0); void loadFeed(true) }}>Обновить ленту</button>
          </div>
        ) : (
          <AnimatePresence mode="wait" initial={false} custom={departure}>
            <motion.div key={game.id} className="discover-deck"
              initial={reducedMotion ? false : { opacity: 0, scale: .993 }}
              animate={{ opacity: 1, scale: 1, x: 0, y: 0 }}
              variants={{ exit: (direction: Direction) => reducedMotion
                ? { opacity: 0 }
                : direction === 'right'
                  ? { x: '115%', opacity: 0, rotate: 7 }
                  : direction === 'left'
                    ? { x: '-115%', opacity: 0, rotate: -7 }
                    : { y: '-110%', opacity: 0, scale: .95 },
              }}
              exit="exit"
              transition={{ duration: .36, ease: [0.22, 1, 0.36, 1] }}>
              <motion.div className="discover-card" style={{ x: cardShift, rotate: cardTilt }}>
                <div className="discover-cover" aria-hidden="true">
                  {game.coverUrl && <img className="discover-cover__ambient" src={game.coverUrl} alt="" />}
                  <div className="discover-cover__poster">
                    <Cover game={game} priority />
                  </div>
                  <div className="discover-cover__fade" />
                </div>
                <motion.div
                  className="discover-cover__gesture"
                  onPan={onPosterPan}
                  onPanEnd={onPosterPanEnd}
                  aria-label={'Свайпы для игры ' + game.title}
                />
                {!helpOpen && !expanded && (
                  <div className="discover-hints" aria-hidden="true">
                    <span className="discover-hint discover-hint--up">↑ Хочу поиграть</span>
                    <span className="discover-hint discover-hint--left">← Не нравится</span>
                    <span className="discover-hint discover-hint--right">Нравится →</span>
                  </div>
                )}

                <motion.div className={expanded ? 'discover-sheet discover-sheet--expanded' : 'discover-sheet'}
                  style={{ height: fullSheetHeight, y: sheetY }}>
                  <button type="button" className="discover-sheet__handle"
                    aria-label={expanded ? 'Свернуть подробности' : 'Развернуть подробности'}
                    aria-expanded={expanded}
                    onPointerDown={onPointerStart}
                    onMouseDown={onMouseStart}
                    onTouchStart={onTouchStart}>
                    <span className={expanded ? 'discover-sheet__chevron discover-sheet__chevron--down' : 'discover-sheet__chevron'} />
                  </button>
                  <div className="discover-sheet__body">
                    <div className="discover-sheet__summary-row">
                      <div className="discover-sheet__identity">
                        <h2>{game.title}</h2>
                        <p>{releaseLabel(game)}</p>
                        <p>{game.genres.slice(0, 2).join(' · ') || 'Жанр не указан'}</p>
                      </div>
                      <div className="discover-sheet__ratings" aria-label="Рейтинги игры">
                        <span className="discover-rating discover-rating--igdb"><small>IGDB</small><strong>{game.igdbRating || '—'}</strong></span>
                        <span className="discover-rating discover-rating--rateapp"><small>Rate APP</small><strong>{game.communityRating || '—'}</strong></span>
                      </div>
                    </div>
                    <motion.div className="discover-sheet__extra"
                      style={{ opacity: detailOpacity, y: detailRise, pointerEvents: expanded ? 'auto' : 'none' }}
                      aria-hidden={!expanded}>
                      {!!game.platforms.length && <p className="discover-sheet__platforms">{game.platforms.slice(0, 4).join(' · ')}</p>}
                      <p className="discover-sheet__description">
                        {detailLoading ? 'Загружаем описание…'
                          : currentDetails?.summary || 'Описание пока недоступно. Можно посмотреть страницу игры в магазине.'}
                      </p>
                      {(!!currentDetails?.storeLinks?.length || !!currentDetails?.trailerUrl) && (
                        <div className="discover-sheet__links">
                          {currentDetails.storeLinks?.map(link => (
                            <a key={link.provider} href={link.url} target="_blank" rel="noopener noreferrer">
                              {link.label} <span aria-hidden="true">↗</span>
                            </a>
                          ))}
                          {!!currentDetails.trailerUrl && <a href={currentDetails.trailerUrl}
                            target="_blank" rel="noopener noreferrer">▶ Трейлер <span aria-hidden="true">↗</span></a>}
                        </div>
                      )}
                    </motion.div>
                  </div>
                </motion.div>
              </motion.div>
            </motion.div>
          </AnimatePresence>
        )}
        {error && <div className="discover-error" role="alert">{error}</div>}
        <AnimatePresence>
          {helpOpen && game && artworkReady && !loading && (
            <motion.div className="discover-guide" role="dialog" aria-modal="true" aria-label="Обучение рекомендациям"
              initial={reducedMotion ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }} transition={{ duration: .32 }}>
              <div className="discover-guide__backdrop" />
              <div className="discover-guide__directions">
                <div className="discover-guide__direction discover-guide__direction--up">
                  <strong>↑ Хочу поиграть</strong><span>В список желаемого</span>
                </div>
                <div className="discover-guide__direction discover-guide__direction--left">
                  <strong>← Не нравится</strong><span>Меньше похожих</span>
                </div>
                <div className="discover-guide__direction discover-guide__direction--right">
                  <strong>Нравится →</strong><span>Больше похожих</span>
                </div>
              </div>
              <div className="discover-guide__panel">
                <span className="discover-guide__eyebrow">RATE APP · DISCOVERY</span>
                <h2>Новые игры для тебя</h2>
                <p>Мы подбираем игры по твоим оценкам и предпочтениям. Проводи пальцем по обложке в нужную сторону — каждый выбор поможет сделать рекомендации точнее.</p>
                <p className="discover-guide__sheet-tip">Чтобы узнать об игре больше, потяни шеврон на стеклянной панели вверх.</p>
                <button type="button" aria-label="Закрыть обучение" onClick={dismissHelp}>Начать</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  )
}
