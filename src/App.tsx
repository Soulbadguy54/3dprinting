import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from 'motion/react'
import AuthScreen, { type AuthUser } from './AuthScreen'
import {
  games,
  type Game,
  type GameCollection,
  type LibraryEntry,
  type LibraryStatus,
} from './data'

type IconName =
  | 'library'
  | 'plus'
  | 'layers'
  | 'user'
  | 'search'
  | 'filter'
  | 'star'
  | 'arrow'
  | 'back'
  | 'calendar'
  | 'gamepad'
  | 'globe'
  | 'mail'
  | 'lock'
  | 'check'
  | 'play'
  | 'bookmark'
  | 'close'
  | 'sort'

type Tab = 'library' | 'add' | 'collections' | 'profile'
type SortMode = 'activity' | 'score-desc' | 'score-asc' | 'title'

type ApiLibraryEntry = Omit<
  LibraryEntry,
  'platform' | 'completedAt' | 'startedAt' | 'score' |
  'atmosphereScore' | 'storyScore' | 'technologyScore' | 'gameplayScore' | 'review'
> & {
  platform: string | null
  completedAt: string | null
  startedAt: string | null
  score: number | null
  atmosphereScore: number | null
  storyScore: number | null
  technologyScore: number | null
  gameplayScore: number | null
  review: string | null
  game?: Game
}

type BootstrapPayload = {
  user: AuthUser
  library: ApiLibraryEntry[]
  collections: GameCollection[]
}

const normalizeEntry = (entry: ApiLibraryEntry | LibraryEntry): LibraryEntry => ({
  ...entry,
  platform: entry.platform ?? undefined,
  completedAt: entry.completedAt ?? undefined,
  startedAt: entry.startedAt ?? undefined,
  score: entry.score ?? undefined,
  atmosphereScore: entry.atmosphereScore ?? undefined,
  storyScore: entry.storyScore ?? undefined,
  technologyScore: entry.technologyScore ?? undefined,
  gameplayScore: entry.gameplayScore ?? undefined,
  review: entry.review ?? undefined,
})

const statusMeta: Record<LibraryStatus, { label: string; short: string }> = {
  completed: { label: 'Пройдено', short: 'Пройдено' },
  playing: { label: 'Прохожу', short: 'Прохожу' },
  wishlist: { label: 'Хочу пройти', short: 'Хочу' },
  dropped: { label: 'Дропнул', short: 'Дроп' },
}

const statusIcons: Record<LibraryStatus, IconName> = {
  completed: 'check',
  playing: 'play',
  wishlist: 'bookmark',
  dropped: 'close',
}

const ratedStatuses = new Set<LibraryStatus>(['completed', 'dropped'])

const preferredPlatform = (platforms: string[]) => {
  const priorities = [
    /^(pc|pc \(microsoft windows\))$/i,
    /windows/i,
    /(playstation 5|\bps5\b)/i,
    /xbox series/i,
    /(playstation 4|\bps4\b)/i,
    /xbox one/i,
    /(nintendo )?switch/i,
  ]

  for (const pattern of priorities) {
    const match = platforms.find((platform) => pattern.test(platform))
    if (match) return match
  }

  return platforms[0] ?? ''
}

function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }

  const paths: Record<IconName, ReactNode> = {
    library: <><path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z"/><path d="M7 20V6a2 2 0 0 0-2-2"/><path d="M9 8h6M9 12h6"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.2 3.5-6.3 8-6.3s7.2 2.1 8 6.3"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    filter: <><path d="M4 6h16"/><path d="M7 12h10"/><path d="M10 18h4"/></>,
    star: <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>,
    arrow: <><path d="M5 12h14"/><path d="m14 7 5 5-5 5"/></>,
    back: <><path d="M19 12H5"/><path d="m10 17-5-5 5-5"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></>,
    gamepad: <><path d="M7 8h10a4 4 0 0 1 3.8 5.2l-1.4 4.2a2 2 0 0 1-3.2.9L14 16h-4l-2.2 2.3a2 2 0 0 1-3.2-.9l-1.4-4.2A4 4 0 0 1 7 8Z"/><path d="M8 11v4M6 13h4"/><circle cx="16.5" cy="12" r=".7" fill="currentColor"/><circle cx="18" cy="14" r=".7" fill="currentColor"/></>,
    globe: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></>,
    mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16.5 9"/></>,
    play: <><circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/></>,
    bookmark: <path d="M6 4.8A1.8 1.8 0 0 1 7.8 3h8.4A1.8 1.8 0 0 1 18 4.8V21l-6-3.8L6 21V4.8Z"/>,
    close: <><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></>,
    sort: <><path d="M8 6h11M8 12h8M8 18h5"/><path d="M4 4v16M2 18l2 2 2-2"/></>,
  }

  return <svg {...common}>{paths[name]}</svg>
}

function formatDate(value?: string) {
  if (!value) return ''
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(`${value}T12:00:00`))
}

function formatCardDate(value?: string) {
  if (!value) return ''
  const [year, month, day] = value.split('-')
  if (!year || !month || !day) return value
  return `${day}.${month}.${year}`
}

function Cover({
  game,
  compact = false,
  markers = [],
}: {
  game: Game
  compact?: boolean
  markers?: GameCollection[]
}) {
  const style = {
    '--cover-accent': game.accent,
    '--cover-accent-2': game.accent2,
  } as CSSProperties

  return (
    <div className={compact ? 'cover cover--compact' : 'cover'} style={style}>
      {game.coverUrl && <img className="cover__image" src={game.coverUrl} alt="" loading="lazy" />}
      {!game.coverUrl && <div className="cover__orb cover__orb--one" />}
      {!game.coverUrl && <div className="cover__orb cover__orb--two" />}
      {!game.coverUrl && <span className="cover__noise" />}
      {!game.coverUrl && <span className="cover__glyph">{game.glyph}</span>}
      {markers.length > 0 && (
        <span className="cover__markers" aria-label="Коллекции">
          {markers.slice(0, 2).map((collection) => (
            <span className="collection-marker" key={collection.id}>{collection.mark}</span>
          ))}
          {markers.length > 2 && <span className="collection-marker">+{markers.length - 2}</span>}
        </span>
      )}
    </div>
  )
}

function GameCard({
  game,
  entry,
  collections,
  onOpen,
  animationIndex = 0,
}: {
  game: Game
  entry: LibraryEntry
  collections: GameCollection[]
  onOpen: () => void
  animationIndex?: number
}) {
  const shouldReduceMotion = useReducedMotion()
  const markers = collections.filter((collection) => entry.collectionIds.includes(collection.id))
  const activityDate =
    entry.status === 'completed' && entry.completedAt
      ? entry.completedAt
      : entry.status === 'playing' && entry.startedAt
        ? entry.startedAt
        : entry.addedAt

  return (
    <motion.button
      layout
      className="game-card"
      onClick={onOpen}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 16, scale: .985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={shouldReduceMotion ? undefined : { opacity: 0, scale: .975 }}
      whileTap={shouldReduceMotion ? undefined : { scale: .985 }}
      transition={{
        type: 'spring',
        stiffness: 430,
        damping: 34,
        mass: .72,
        delay: shouldReduceMotion ? 0 : Math.min(animationIndex * .025, .16),
      }}
    >
      <div className="game-card__cover-wrap">
        <Cover game={game} markers={markers} />
        {entry.score != null && (
          <span className="score-badge"><Icon name="star" size={13} />{entry.score.toFixed(1)}</span>
        )}
        <span className={`status-badge status-badge--${entry.status}`}>
          <Icon name={statusIcons[entry.status]} size={12} />
          <span className="status-badge__label">{statusMeta[entry.status].short}</span>
          <span className="status-badge__date">{formatCardDate(activityDate)}</span>
        </span>
      </div>
      <div className="game-card__body">
        <h3>{game.title}</h3>
      </div>
    </motion.button>
  )
}

function RatingSlider({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (value: number) => void
}) {
  return (
    <label className="rating-slider">
      <span className="rating-slider__header">
        <strong>{label}</strong>
        <b>{value.toFixed(1)}</b>
      </span>
      <input
        type="range"
        min="1"
        max="10"
        step="0.1"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}

function App() {
  const shouldReduceMotion = useReducedMotion()
  const [activeTab, setActiveTab] = useState<Tab>('library')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [entries, setEntries] = useState<LibraryEntry[]>([])
  const [collections, setCollections] = useState<GameCollection[]>([])
  const [catalogGames, setCatalogGames] = useState<Game[]>(games)
  const [addResults, setAddResults] = useState<Game[]>([])
  const [addSearchLoading, setAddSearchLoading] = useState(false)
  const [addSearchError, setAddSearchError] = useState('')
  const addSearchCache = useRef(new Map<string, Game[]>())
  const [query, setQuery] = useState('')
  const [statusFilters, setStatusFilters] = useState<LibraryStatus[]>([])
  const [genreFilter, setGenreFilter] = useState('all')
  const [platformFilter, setPlatformFilter] = useState('all')
  const [sortMode, setSortMode] = useState<SortMode>('activity')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [librarySearchOpen, setLibrarySearchOpen] = useState(false)
  const librarySearchInputRef = useRef<HTMLInputElement>(null)
  const focusLibrarySearchOnOpen = useRef(false)
  const [selectedGameId, setSelectedGameId] = useState<number | null>(null)
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null)
  const [collectionCreatorOpen, setCollectionCreatorOpen] = useState(false)
  const [collectionTitle, setCollectionTitle] = useState('')
  const [collectionDescription, setCollectionDescription] = useState('')
  const [collectionMark, setCollectionMark] = useState('')
  const [collectionSaving, setCollectionSaving] = useState(false)
  const [collectionError, setCollectionError] = useState('')

  const [addQuery, setAddQuery] = useState('')
  const [addGameId, setAddGameId] = useState<number | null>(null)
  const [addStatus, setAddStatus] = useState<LibraryStatus>('completed')
  const [addPlatform, setAddPlatform] = useState('')
  const [addDate, setAddDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [addAtmosphereScore, setAddAtmosphereScore] = useState(8)
  const [addStoryScore, setAddStoryScore] = useState(8)
  const [addTechnologyScore, setAddTechnologyScore] = useState(8)
  const [addGameplayScore, setAddGameplayScore] = useState(8)
  const [addReview, setAddReview] = useState('')
  const [addReviewOpen, setAddReviewOpen] = useState(false)
  const [addCollectionIds, setAddCollectionIds] = useState<string[]>([])

  const calculatedAddScore = Number((
    (addAtmosphereScore + addStoryScore + addTechnologyScore + addGameplayScore) / 4
  ).toFixed(1))

  const applyBootstrap = (payload: BootstrapPayload) => {
    setAuthUser(payload.user)
    setEntries(payload.library.map(normalizeEntry))
    setCollections(payload.collections)

    const libraryMetadata = payload.library.flatMap((entry) => entry.game ? [entry.game] : [])
    setCatalogGames((current) => {
      const merged = new Map(current.map((game) => [game.id, game]))
      libraryMetadata.forEach((game) => merged.set(game.id, game))
      return Array.from(merged.values())
    })
  }

  const hydrateAfterLogin = async (fallbackUser: AuthUser) => {
    setAuthUser(fallbackUser)
    setAuthReady(true)

    try {
      const response = await fetch('/api/bootstrap')
      if (!response.ok) return
      applyBootstrap(await response.json() as BootstrapPayload)
    } catch {
      // Login itself succeeded; keep the authenticated shell and retry on refresh.
    }
  }

  useEffect(() => {
    let cancelled = false

    const restoreSession = async () => {
      try {
        const response = await fetch('/api/bootstrap')
        if (!response.ok) {
          if (!cancelled) setAuthUser(null)
          return
        }

        const payload = await response.json() as BootstrapPayload
        if (!cancelled) applyBootstrap(payload)
      } catch {
        if (!cancelled) setAuthUser(null)
      } finally {
        if (!cancelled) setAuthReady(true)
      }
    }

    void restoreSession()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (
      activeTab !== 'library' ||
      !librarySearchOpen ||
      !focusLibrarySearchOnOpen.current
    ) return

    focusLibrarySearchOnOpen.current = false
    const frame = window.requestAnimationFrame(() => {
      librarySearchInputRef.current?.focus()
    })

    return () => window.cancelAnimationFrame(frame)
  }, [activeTab, librarySearchOpen])

  const entryMap = useMemo(
    () => new Map(entries.map((entry) => [entry.gameId, entry])),
    [entries],
  )

  const availableGenres = useMemo(() => {
    const libraryGameIds = new Set(entries.map((entry) => entry.gameId))
    return Array.from(
      new Set(
        catalogGames
          .filter((game) => libraryGameIds.has(game.id))
          .flatMap((game) => game.genres),
      ),
    ).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [entries, catalogGames])

  const availablePlatforms = useMemo(() => {
    return Array.from(
      new Set(entries.map((entry) => entry.platform).filter((platform): platform is string => Boolean(platform))),
    ).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [entries])

  const libraryGames = useMemo(() => {
    const normalized = query.trim().toLowerCase()

    const result = entries
      .filter((entry) => statusFilters.length === 0 || statusFilters.includes(entry.status))
      .map((entry) => ({ entry, game: catalogGames.find((game) => game.id === entry.gameId)! }))
      .filter(({ game, entry }) => {
        const queryMatch =
          !normalized ||
          game.title.toLowerCase().includes(normalized) ||
          game.genres.some((genre) => genre.toLowerCase().includes(normalized)) ||
          game.developer.toLowerCase().includes(normalized)
        const genreMatch = genreFilter === 'all' || game.genres.includes(genreFilter)
        const platformMatch = platformFilter === 'all' || entry.platform === platformFilter

        return queryMatch && genreMatch && platformMatch
      })

    return result.sort((a, b) => {
      if (sortMode === 'score-desc') {
        return (b.entry.score ?? -1) - (a.entry.score ?? -1)
      }

      if (sortMode === 'score-asc') {
        const scoreA = a.entry.score ?? Number.POSITIVE_INFINITY
        const scoreB = b.entry.score ?? Number.POSITIVE_INFINITY
        return scoreA - scoreB
      }

      if (sortMode === 'title') {
        return a.game.title.localeCompare(b.game.title, 'ru')
      }

      const dateA = a.entry.completedAt ?? a.entry.startedAt ?? a.entry.addedAt
      const dateB = b.entry.completedAt ?? b.entry.startedAt ?? b.entry.addedAt
      return dateB.localeCompare(dateA)
    })
  }, [entries, query, statusFilters, genreFilter, platformFilter, sortMode, catalogGames])

  const activeExtraFilters =
    (genreFilter !== 'all' ? 1 : 0) +
    (platformFilter !== 'all' ? 1 : 0)

  const resetExtraFilters = () => {
    setGenreFilter('all')
    setPlatformFilter('all')
  }

  useEffect(() => {
    const query = addQuery.trim()
    const cacheKey = query.toLocaleLowerCase('ru-RU')

    if (query.length < 3) {
      setAddResults([])
      setAddSearchError('')
      setAddSearchLoading(false)
      return
    }

    const cached = addSearchCache.current.get(cacheKey)
    if (cached) {
      setAddResults(cached)
      setAddSearchError('')
      setAddSearchLoading(false)
      return
    }

    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setAddSearchLoading(true)
      setAddSearchError('')

      try {
        const response = await fetch(`/api/games/search?q=${encodeURIComponent(query)}`, {
          signal: controller.signal,
        })
        const payload = await response.json().catch(() => null) as Game[] | { detail?: string } | null

        if (!response.ok) {
          const detail = payload && !Array.isArray(payload) && payload.detail
          setAddResults([])
          setAddSearchError(detail || 'Не удалось выполнить поиск.')
          return
        }

        const results = Array.isArray(payload) ? payload : []
        addSearchCache.current.set(cacheKey, results)
        if (addSearchCache.current.size > 30) {
          const oldestKey = addSearchCache.current.keys().next().value
          if (oldestKey) addSearchCache.current.delete(oldestKey)
        }

        setAddResults(results)
        setCatalogGames((current) => {
          const merged = new Map(current.map((game) => [game.id, game]))
          results.forEach((game) => merged.set(game.id, game))
          return Array.from(merged.values())
        })
      } catch (error) {
        if ((error as Error).name !== 'AbortError') {
          setAddResults([])
          setAddSearchError('Не удалось связаться с IGDB.')
        }
      } finally {
        if (!controller.signal.aborted) setAddSearchLoading(false)
      }
    }, 650)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [addQuery])

  const counts = useMemo(() => ({
    completed: entries.filter((entry) => entry.status === 'completed').length,
    playing: entries.filter((entry) => entry.status === 'playing').length,
    wishlist: entries.filter((entry) => entry.status === 'wishlist').length,
    dropped: entries.filter((entry) => entry.status === 'dropped').length,
  }), [entries])

  const averageLibraryScore = useMemo(() => {
    const scores = entries
      .map((entry) => entry.score)
      .filter((score): score is number => score != null)

    if (scores.length === 0) return null
    return scores.reduce((sum, score) => sum + score, 0) / scores.length
  }, [entries])

  const toggleStatusFilter = (status: LibraryStatus) => {
    setStatusFilters((current) =>
      current.includes(status)
        ? current.filter((item) => item !== status)
        : [...current, status],
    )
  }

  const openTab = (tab: Tab) => {
    setActiveTab(tab)
    setSelectedGameId(null)
    setSelectedCollectionId(null)
  }

  const startAdding = (game: Game) => {
    setAddGameId(game.id)
    setAddStatus('completed')
    setAddPlatform(preferredPlatform(game.platforms))
    setAddDate(new Date().toISOString().slice(0, 10))
    setAddAtmosphereScore(8)
    setAddStoryScore(8)
    setAddTechnologyScore(8)
    setAddGameplayScore(8)
    setAddReview('')
    setAddReviewOpen(false)
    setAddCollectionIds([])
    setSelectedGameId(null)
    setActiveTab('add')
  }

  const startEditing = (game: Game, entry: LibraryEntry) => {
    setAddGameId(game.id)
    setAddStatus(entry.status)
    setAddPlatform(entry.platform ?? preferredPlatform(game.platforms))
    setAddDate(entry.completedAt ?? new Date().toISOString().slice(0, 10))
    const fallbackScore = entry.score ?? 8
    setAddAtmosphereScore(entry.atmosphereScore ?? fallbackScore)
    setAddStoryScore(entry.storyScore ?? fallbackScore)
    setAddTechnologyScore(entry.technologyScore ?? fallbackScore)
    setAddGameplayScore(entry.gameplayScore ?? fallbackScore)
    setAddReview(entry.review ?? '')
    setAddReviewOpen(Boolean(entry.review))
    setAddCollectionIds(entry.collectionIds)
    setSelectedGameId(null)
    setActiveTab('add')
  }

  const saveGame = async () => {
    const game = catalogGames.find((item) => item.id === addGameId)
    if (!game) return

    const today = new Date().toISOString().slice(0, 10)
    const nextEntry: LibraryEntry = {
      gameId: game.id,
      status: addStatus,
      platform: addStatus === 'wishlist' ? undefined : addPlatform,
      completedAt: addStatus === 'completed' ? addDate : undefined,
      startedAt: addStatus === 'playing' ? today : undefined,
      score: ratedStatuses.has(addStatus) ? calculatedAddScore : undefined,
      atmosphereScore: ratedStatuses.has(addStatus) ? addAtmosphereScore : undefined,
      storyScore: ratedStatuses.has(addStatus) ? addStoryScore : undefined,
      technologyScore: ratedStatuses.has(addStatus) ? addTechnologyScore : undefined,
      gameplayScore: ratedStatuses.has(addStatus) ? addGameplayScore : undefined,
      review: ratedStatuses.has(addStatus) ? (addReview.trim() || undefined) : undefined,
      collectionIds: addCollectionIds,
      addedAt: entryMap.get(game.id)?.addedAt ?? today,
    }

    try {
      const response = await fetch(`/api/library/${game.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextEntry),
      })

      if (response.ok) {
        const savedEntry = normalizeEntry(await response.json() as ApiLibraryEntry)
        setEntries((current) => [...current.filter((entry) => entry.gameId !== game.id), savedEntry])
      } else {
        setEntries((current) => [...current.filter((entry) => entry.gameId !== game.id), nextEntry])
      }
    } catch {
      setEntries((current) => [...current.filter((entry) => entry.gameId !== game.id), nextEntry])
    }

    setAddGameId(null)
    setAddQuery('')
    setSelectedGameId(game.id)
    setActiveTab('library')
  }

  const deleteGame = async (game: Game) => {
    if (!window.confirm(`Удалить «${game.title}» из моих игр?`)) return

    try {
      const response = await fetch(`/api/library/${game.id}`, { method: 'DELETE' })
      if (!response.ok) {
        window.alert('Не удалось удалить игру. Попробуйте ещё раз.')
        return
      }

      setEntries((current) => current.filter((entry) => entry.gameId !== game.id))
      setSelectedGameId(null)
      if (addGameId === game.id) setAddGameId(null)
    } catch {
      window.alert('Не удалось удалить игру. Проверьте соединение и попробуйте ещё раз.')
    }
  }

  const createCollection = async () => {
    const title = collectionTitle.trim()
    if (!title || collectionSaving) return

    setCollectionSaving(true)
    setCollectionError('')

    try {
      const response = await fetch('/api/collections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          description: collectionDescription.trim() || undefined,
          mark: collectionMark.trim() || undefined,
        }),
      })
      const payload = await response.json().catch(() => null) as GameCollection | { detail?: string } | null

      if (!response.ok || !payload || !('id' in payload)) {
        setCollectionError(
          payload && 'detail' in payload && payload.detail
            ? payload.detail
            : 'Не удалось создать коллекцию.',
        )
        return
      }

      setCollections((current) => [...current, payload])
      setCollectionTitle('')
      setCollectionDescription('')
      setCollectionMark('')
      setCollectionCreatorOpen(false)
      setSelectedCollectionId(payload.id)
    } catch {
      setCollectionError('Не удалось создать коллекцию. Проверьте соединение.')
    } finally {
      setCollectionSaving(false)
    }
  }

  const toggleAddCollection = (collectionId: string) => {
    setAddCollectionIds((current) =>
      current.includes(collectionId)
        ? current.filter((id) => id !== collectionId)
        : [...current, collectionId],
    )
  }

  const selectedEntry = selectedGameId ? entryMap.get(selectedGameId) : undefined
  const selectedGame = selectedGameId ? catalogGames.find((game) => game.id === selectedGameId) : undefined

  const renderDetail = () => {
    if (!selectedGame || !selectedEntry) return null
    const gameCollections = collections.filter((collection) => selectedEntry.collectionIds.includes(collection.id))

    return (
      <div className="detail-page">
        <button className="icon-button detail-back" onClick={() => setSelectedGameId(null)}>
          <Icon name="back" size={20} />
        </button>

        <section className="detail-hero">
          <div className="detail-hero__cover"><Cover game={selectedGame} markers={gameCollections} /></div>
          <div className="detail-hero__info">
            <h1>{selectedGame.title}</h1>
            <p>{selectedGame.genres.join(' · ')} · {selectedGame.year}</p>
            <button
              className="secondary-button"
              onClick={() => startEditing(selectedGame, selectedEntry)}
            >
              Редактировать запись
            </button>
          </div>
        </section>

        <section className="rating-grid">
          <div className="rating-card rating-card--mine">
            <span>Моя оценка</span>
            <strong>{selectedEntry.score != null ? selectedEntry.score.toFixed(1) : '—'}</strong>
            <small>из 10</small>
          </div>
          <div className="rating-card">
            <span>RateApp</span>
            <strong>{selectedGame.communityRatings > 0 ? selectedGame.communityRating.toFixed(1) : '—'}</strong>
            <small>{selectedGame.communityRatings > 0 ? `${selectedGame.communityRatings.toLocaleString('ru-RU')} оценок` : 'оценок пока нет'}</small>
          </div>
          <div className="rating-card">
            <span>IGDB</span>
            <strong>{selectedGame.igdbRating}</strong>
            <small>из 100</small>
          </div>
        </section>

        {ratedStatuses.has(selectedEntry.status) && (
          <section className="criteria-card">
            <div className="criteria-card__header">
              <span className="eyebrow">МОЯ ОЦЕНКА</span>
              <strong>{selectedEntry.score?.toFixed(1) ?? '—'}</strong>
            </div>
            <div className="criteria-breakdown">
              <div><span>Атмосфера</span><b>{selectedEntry.atmosphereScore?.toFixed(1) ?? '—'}</b></div>
              <div><span>Сюжет</span><b>{selectedEntry.storyScore?.toFixed(1) ?? '—'}</b></div>
              <div><span>Технологичность</span><b>{selectedEntry.technologyScore?.toFixed(1) ?? '—'}</b></div>
              <div><span>Геймплей</span><b>{selectedEntry.gameplayScore?.toFixed(1) ?? '—'}</b></div>
            </div>
          </section>
        )}

        <section className="info-card">
          <div className="section-heading section-heading--tight">
            <div>
              <span className="eyebrow">МОЯ ЗАПИСЬ</span>
              <h2>Прохождение</h2>
            </div>
          </div>
          <div className="info-list">
            <div><span><Icon name="gamepad" size={17} />Платформа</span><strong>{selectedEntry.platform ?? 'Не указана'}</strong></div>
            <div><span><Icon name="calendar" size={17} />Дата прохождения</span><strong>{selectedEntry.completedAt ? formatDate(selectedEntry.completedAt) : '—'}</strong></div>
            <div><span><Icon name="layers" size={17} />Коллекции</span><strong>{gameCollections.length || '—'}</strong></div>
          </div>
          {selectedEntry.review && (
            <div className="review-box">
              <span>Мой отзыв</span>
              <p>{selectedEntry.review}</p>
            </div>
          )}
          {gameCollections.length > 0 && (
            <div className="tag-list">
              {gameCollections.map((collection) => (
                <span className="collection-tag" key={collection.id}>
                  <b>{collection.mark}</b>{collection.title}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="info-card">
          <span className="eyebrow">ОБ ИГРЕ</span>
          <h2>{selectedGame.developer}</h2>
          <div className="facts-grid">
            <div><span>Релиз</span><strong>{formatDate(selectedGame.releaseDate)}</strong></div>
            <div><span>Платформы</span><strong>{selectedGame.platforms.join(', ')}</strong></div>
            <div><span>Жанры</span><strong>{selectedGame.genres.join(', ')}</strong></div>
          </div>
        </section>

        <button className="danger-button" onClick={() => { void deleteGame(selectedGame) }}>
          Удалить из моих игр
        </button>
      </div>
    )
  }

  const renderLibrary = () => (
    <LayoutGroup id="library-motion">
      <header className="topbar library-topbar">
        <motion.button
          layout
          className={statusFilters.length === 0 ? 'library-title library-title--active' : 'library-title'}
          onClick={() => setStatusFilters([])}
          aria-label="Показать все игры"
          aria-pressed={statusFilters.length === 0}
          whileTap={shouldReduceMotion ? undefined : { scale: .985 }}
          transition={{ type: 'spring', stiffness: 480, damping: 34 }}
        >
          Мои игры
        </motion.button>

        <motion.div className="topbar-actions" layout>
          <motion.button
            className={librarySearchOpen || query ? 'icon-button library-search-trigger library-search-trigger--active' : 'icon-button library-search-trigger'}
            onClick={() => {
              if (librarySearchOpen) {
                focusLibrarySearchOnOpen.current = false
                librarySearchInputRef.current?.blur()
                setLibrarySearchOpen(false)
                setQuery('')
              } else {
                focusLibrarySearchOnOpen.current = true
                setLibrarySearchOpen(true)
              }
            }}
            aria-label={librarySearchOpen ? 'Свернуть поиск' : 'Открыть поиск'}
            aria-expanded={librarySearchOpen}
            whileTap={shouldReduceMotion ? undefined : { scale: .9 }}
            transition={{ type: 'spring', stiffness: 520, damping: 36, mass: .7 }}
          >
            <Icon name="search" size={19} />
          </motion.button>
          <motion.button
            layout
            className="round-add"
            onClick={() => openTab('add')}
            aria-label="Добавить игру"
            whileTap={shouldReduceMotion ? undefined : { scale: .9, rotate: 8 }}
            transition={{ type: 'spring', stiffness: 520, damping: 30 }}
          >
            <Icon name="plus" size={20} />
          </motion.button>
        </motion.div>
      </header>

      <AnimatePresence initial={false}>
        {librarySearchOpen && (
          <motion.div
            key="library-search-panel"
            className="library-search-motion-wrap"
            initial={shouldReduceMotion ? false : { height: 0, opacity: 0, y: -8 }}
            animate={{ height: 'auto', opacity: 1, y: 0 }}
            exit={shouldReduceMotion ? undefined : { height: 0, opacity: 0, y: -6 }}
            transition={{ duration: .2, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="search-wrap library-search">
              <Icon name="search" size={19} />
              <input
                ref={librarySearchInputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Название, жанр или разработчик..."
                aria-label="Поиск в библиотеке"
              />
              {query && (
                <motion.button
                  className="library-search__clear"
                  onClick={() => {
                    setQuery('')
                    librarySearchInputRef.current?.focus()
                  }}
                  aria-label="Очистить поиск"
                  whileTap={shouldReduceMotion ? undefined : { scale: .88 }}
                >
                  <Icon name="close" size={17} />
                </motion.button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.section
        className="library-overview"
        aria-label="Сводка библиотеки"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: .24 }}
      >
        <motion.div
          className="library-overview-card library-overview-card--games"
          initial={shouldReduceMotion ? false : { opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ type: 'spring', stiffness: 380, damping: 30, delay: .03 }}
        >
          <span className="library-overview-card__icon"><Icon name="gamepad" size={20} /></span>
          <span>
            <small>Всего игр</small>
            <strong>{entries.length}</strong>
          </span>
        </motion.div>
        <motion.div
          className="library-overview-card library-overview-card--score"
          initial={shouldReduceMotion ? false : { opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ type: 'spring', stiffness: 380, damping: 30, delay: .07 }}
        >
          <span className="library-overview-card__icon"><Icon name="star" size={19} /></span>
          <span>
            <small>Средняя оценка</small>
            <strong>{averageLibraryScore != null ? averageLibraryScore.toFixed(1) : '—'}</strong>
          </span>
        </motion.div>
      </motion.section>

      <motion.section
        className="library-summary"
        aria-label="Фильтр по статусу"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: .24, delay: .08 }}
      >
        {([
          ['completed', 'Пройдено'],
          ['playing', 'Прохожу'],
          ['wishlist', 'Хочу пройти'],
          ['dropped', 'Дропнул'],
        ] as [LibraryStatus, string][]).map(([status, label]) => (
          <motion.button
            layout
            key={status}
            className={
              statusFilters.includes(status)
                ? `library-status-card library-status-card--${status} library-status-card--active`
                : `library-status-card library-status-card--${status}`
            }
            onClick={() => toggleStatusFilter(status)}
            aria-pressed={statusFilters.includes(status)}
            whileHover={shouldReduceMotion ? undefined : { y: -2 }}
            whileTap={shouldReduceMotion ? undefined : { scale: .965 }}
            transition={{ type: 'spring', stiffness: 460, damping: 30 }}
          >
            <motion.span
              className="library-status-card__icon"
              animate={shouldReduceMotion ? undefined : {
                scale: statusFilters.includes(status) ? 1.06 : 1,
                rotate: statusFilters.includes(status) ? 2 : 0,
              }}
            >
              <Icon name={statusIcons[status]} size={18} />
            </motion.span>
            <span className="library-status-card__copy">
              <strong>{counts[status]}</strong>
              <span>{label}</span>
            </span>
          </motion.button>
        ))}
      </motion.section>

      <motion.div
        className="library-controls"
        layout
        initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: .22, delay: .12 }}
      >
        <label className="library-sort">
          <Icon name="sort" size={17} />
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)} aria-label="Сортировка">
            <option value="activity">Последняя активность</option>
            <option value="score-desc">Оценка: высокая → низкая</option>
            <option value="score-asc">Оценка: низкая → высокая</option>
            <option value="title">По названию</option>
          </select>
        </label>

        <button
          className={filtersOpen || activeExtraFilters > 0 ? 'library-filter-button library-filter-button--active' : 'library-filter-button'}
          aria-label="Фильтры библиотеки"
          aria-expanded={filtersOpen}
          onClick={() => setFiltersOpen((current) => !current)}
        >
          <Icon name="filter" size={17} />
          <span>Фильтры</span>
          {activeExtraFilters > 0 && <b>{activeExtraFilters}</b>}
        </button>
      </motion.div>

      <AnimatePresence initial={false}>
        {filtersOpen && (
        <motion.section
          className="filter-panel library-filter-panel"
          initial={shouldReduceMotion ? false : { opacity: 0, y: -8, scaleY: .96 }}
          animate={{ opacity: 1, y: 0, scaleY: 1 }}
          exit={shouldReduceMotion ? undefined : { opacity: 0, y: -6, scaleY: .97 }}
          transition={{ type: 'spring', stiffness: 420, damping: 32, mass: .78 }}
          style={{ transformOrigin: 'top center' }}
        >
          <div className="filter-panel__header">
            <strong>Фильтры библиотеки</strong>
            <div className="filter-panel__actions">
              {activeExtraFilters > 0 && <button onClick={resetExtraFilters}>Сбросить</button>}
              <button onClick={() => setFiltersOpen(false)} aria-label="Закрыть фильтры">
                <Icon name="close" size={16} />
              </button>
            </div>
          </div>

          <div className="filter-group">
            <span>Жанр</span>
            <div className="filter-options">
              <button
                className={genreFilter === 'all' ? 'filter-option filter-option--active' : 'filter-option'}
                onClick={() => setGenreFilter('all')}
              >
                Все
              </button>
              {availableGenres.map((genre) => (
                <button
                  key={genre}
                  className={genreFilter === genre ? 'filter-option filter-option--active' : 'filter-option'}
                  onClick={() => setGenreFilter(genre)}
                >
                  {genre}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-group">
            <span>Платформа</span>
            <div className="filter-options">
              <button
                className={platformFilter === 'all' ? 'filter-option filter-option--active' : 'filter-option'}
                onClick={() => setPlatformFilter('all')}
              >
                Все
              </button>
              {availablePlatforms.map((platform) => (
                <button
                  key={platform}
                  className={platformFilter === platform ? 'filter-option filter-option--active' : 'filter-option'}
                  onClick={() => setPlatformFilter(platform)}
                >
                  {platform}
                </button>
              ))}
            </div>
          </div>
        </motion.section>
        )}
      </AnimatePresence>

      <section className="catalog">
        <AnimatePresence initial={false}>
          {query && (
            <motion.div
              className="section-heading library-section-heading"
              initial={shouldReduceMotion ? false : { opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={shouldReduceMotion ? undefined : { opacity: 0, y: -4 }}
            >
              <h2>Найдено: {libraryGames.length}</h2>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence mode="popLayout" initial={false}>
          {libraryGames.length > 0 ? (
            <motion.div
              key="library-game-grid"
              className="game-grid"
              layout
              initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={shouldReduceMotion ? undefined : { opacity: 0, y: -8 }}
              transition={{ duration: .2, ease: [0.22, 1, 0.36, 1] }}
            >
              <AnimatePresence mode="popLayout">
                {libraryGames.map(({ game, entry }, index) => (
                  <GameCard
                    key={game.id}
                    game={game}
                    entry={entry}
                    collections={collections}
                    onOpen={() => setSelectedGameId(game.id)}
                    animationIndex={index}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          ) : (
            <motion.div
              key="library-empty-state"
              className="empty-state"
              initial={shouldReduceMotion ? false : { opacity: 0, y: 8, scale: .98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={shouldReduceMotion ? undefined : { opacity: 0, y: -8, scale: .98 }}
              transition={{ duration: .18 }}
            >
              <strong>Здесь пока пусто</strong>
              <p>Смени фильтр или добавь новую игру в библиотеку.</p>
              <button onClick={() => openTab('add')}>Добавить игру</button>
            </motion.div>
          )}
        </AnimatePresence>
      </section>
    </LayoutGroup>
  )

  const renderAdd = () => {
    const addGame = addGameId ? catalogGames.find((game) => game.id === addGameId) : undefined
    const editingEntry = addGame ? entryMap.get(addGame.id) : undefined

    if (addGame) {
      return (
        <>
          <header className="subpage-header">
            <button className="icon-button" onClick={() => setAddGameId(null)}><Icon name="back" size={20} /></button>
            <div>
              <h1>{editingEntry ? 'Изменить игру' : statusMeta[addStatus].label}</h1>
            </div>
          </header>

          <section className="add-selected">
            <div className="add-selected__cover"><Cover game={addGame} compact /></div>
            <div>
              <strong>{addGame.title}</strong>
              <span>{addGame.year} · {addGame.genres.join(' · ')}</span>
            </div>
          </section>

          <section className="form-card">
            <label className="field-label">Статус</label>
            <div className="choice-grid">
              {(['completed', 'playing', 'dropped', 'wishlist'] as LibraryStatus[]).map((status) => (
                <button
                  key={status}
                  className={addStatus === status ? 'choice-button choice-button--active' : 'choice-button'}
                  onClick={() => setAddStatus(status)}
                >
                  {statusMeta[status].label}
                </button>
              ))}
            </div>

            {addStatus !== 'wishlist' && (
              <label className="form-field">
                <span>Платформа</span>
                <select value={addPlatform} onChange={(event) => setAddPlatform(event.target.value)}>
                  {addGame.platforms.map((platform) => <option key={platform}>{platform}</option>)}
                </select>
              </label>
            )}

            {addStatus === 'completed' && (
              <label className="form-field">
                <span>Дата прохождения</span>
                <input type="date" value={addDate} onChange={(event) => setAddDate(event.target.value)} />
                <small>По умолчанию — сегодня. Можно указать любую прошлую дату.</small>
              </label>
            )}

            {ratedStatuses.has(addStatus) && (
              <div className="rating-builder">
                  <div className="rating-builder__summary">
                    <span>Итоговая оценка</span>
                    <strong>{calculatedAddScore.toFixed(1)}</strong>
                    <small>среднее четырёх критериев</small>
                  </div>
                  <RatingSlider label="Атмосфера" value={addAtmosphereScore} onChange={setAddAtmosphereScore} />
                  <RatingSlider label="Сюжет" value={addStoryScore} onChange={setAddStoryScore} />
                  <RatingSlider label="Технологичность" value={addTechnologyScore} onChange={setAddTechnologyScore} />
                <RatingSlider label="Геймплей" value={addGameplayScore} onChange={setAddGameplayScore} />
              </div>
            )}

            {ratedStatuses.has(addStatus) && (
              <details
                className="review-editor"
                open={addReviewOpen}
                onToggle={(event) => setAddReviewOpen(event.currentTarget.open)}
              >
                <summary>
                  <span>
                    <strong>{addReview ? 'Мой отзыв' : 'Добавить отзыв'}</strong>
                    <small>необязательно</small>
                  </span>
                  <b>{addReviewOpen ? '−' : '+'}</b>
                </summary>
                <textarea
                  value={addReview}
                  onChange={(event) => setAddReview(event.target.value)}
                  maxLength={5000}
                  placeholder="Что запомнилось, что понравилось или не понравилось?"
                  rows={5}
                />
                <small className="review-editor__counter">{addReview.length}/5000</small>
              </details>
            )}

            <div className="form-field">
              <span>Коллекции <small>необязательно</small></span>
              <div className="collection-choices">
                {collections.map((collection) => (
                  <button
                    key={collection.id}
                    className={addCollectionIds.includes(collection.id) ? 'collection-choice collection-choice--active' : 'collection-choice'}
                    onClick={() => toggleAddCollection(collection.id)}
                  >
                    <b>{collection.mark}</b>
                    <span>{collection.title}</span>
                  </button>
                ))}
              </div>
            </div>

            <button className="primary-button" onClick={saveGame}>
              {editingEntry ? 'Сохранить изменения' : 'Сохранить в библиотеку'}
            </button>
            {editingEntry && (
              <button className="danger-button danger-button--inside" onClick={() => { void deleteGame(addGame) }}>
                Удалить из моих игр
              </button>
            )}
          </section>
        </>
      )
    }

    return (
      <>
        <header className="topbar">
          <div>
            <h1>Добавить игру</h1>
          </div>
        </header>

        <p className="page-lead">Найди игру, а затем укажи статус, платформу, дату и свою оценку.</p>

        <div className="search-wrap">
          <Icon name="search" size={20} />
          <input
            value={addQuery}
            onChange={(event) => setAddQuery(event.target.value)}
            placeholder="Название игры..."
            aria-label="Поиск игры"
          />
          <span className="source-badge">IGDB</span>
        </div>

        {addQuery.trim().length < 3 && (
          <div className="search-hint">Введи хотя бы 3 символа — поиск начнётся после короткой паузы.</div>
        )}
        {addSearchLoading && <div className="search-hint">Ищем в IGDB…</div>}
        {addSearchError && <div className="search-hint search-hint--error">{addSearchError}</div>}

        <section className="search-results">
          {addResults.map((game) => {
            const existing = entryMap.get(game.id)
            return (
              <div className="search-result" key={game.id}>
                <div className="search-result__cover"><Cover game={game} compact /></div>
                <div className="search-result__copy">
                  <strong>{game.title}</strong>
                  <span>{game.year} · {game.genres.slice(0, 2).join(' · ')}</span>
                  <small>{game.platforms.join(' · ')}</small>
                </div>
                <button
                  className={existing ? 'result-action result-action--existing' : 'result-action'}
                  onClick={() => {
                    if (existing) {
                      startEditing(game, existing)
                    } else {
                      startAdding(game)
                    }
                  }}
                >
                  {existing ? 'Изменить' : <Icon name="plus" size={18} />}
                </button>
              </div>
            )
          })}
        </section>
      </>
    )
  }

  const renderCollections = () => {
    if (selectedCollectionId) {
      const collection = collections.find((item) => item.id === selectedCollectionId)
      if (!collection) return null
      const collectionEntries = entries.filter((entry) => entry.collectionIds.includes(collection.id))

      return (
        <>
          <header className="subpage-header">
            <button className="icon-button" onClick={() => setSelectedCollectionId(null)}><Icon name="back" size={20} /></button>
            <div>
              <h1>{collection.title}</h1>
            </div>
          </header>
          <p className="page-lead">{collection.description}</p>
          <div className="game-grid">
            {collectionEntries.map((entry) => {
              const game = catalogGames.find((item) => item.id === entry.gameId)!
              return <GameCard key={game.id} game={game} entry={entry} collections={collections} onOpen={() => setSelectedGameId(game.id)} />
            })}
          </div>
        </>
      )
    }

    return (
      <>
        <header className="topbar">
          <div>
            <h1>Коллекции</h1>
          </div>
          <button
            className="round-add"
            aria-label="Создать коллекцию"
            onClick={() => {
              setCollectionCreatorOpen((current) => !current)
              setCollectionError('')
            }}
          >
            <Icon name="plus" size={20} />
          </button>
        </header>
        <p className="page-lead">Собирай игры в свои списки. Одна игра может быть сразу в нескольких коллекциях.</p>

        {collectionCreatorOpen && (
          <section className="collection-create-card">
            <div className="collection-create-card__heading">
              <strong>Новая коллекция</strong>
              <button
                onClick={() => {
                  setCollectionCreatorOpen(false)
                  setCollectionError('')
                }}
              >
                ×
              </button>
            </div>

            <label className="collection-create-field">
              <span>Название</span>
              <input
                value={collectionTitle}
                onChange={(event) => setCollectionTitle(event.target.value)}
                maxLength={100}
                placeholder="Например, Лучшие RPG"
                autoFocus
              />
            </label>

            <label className="collection-create-field">
              <span>Описание <small>необязательно</small></span>
              <textarea
                value={collectionDescription}
                onChange={(event) => setCollectionDescription(event.target.value)}
                maxLength={500}
                rows={3}
                placeholder="Коротко о том, что здесь собрано"
              />
            </label>

            <label className="collection-create-field collection-create-field--mark">
              <span>Метка <small>до 8 символов</small></span>
              <input
                value={collectionMark}
                onChange={(event) => setCollectionMark(event.target.value)}
                maxLength={8}
                placeholder="RPG"
              />
            </label>

            {collectionError && <p className="collection-create-error">{collectionError}</p>}

            <button
              className="primary-button collection-create-submit"
              onClick={() => { void createCollection() }}
              disabled={!collectionTitle.trim() || collectionSaving}
            >
              {collectionSaving ? 'Создаём…' : 'Создать коллекцию'}
            </button>
          </section>
        )}

        {collections.length === 0 && !collectionCreatorOpen && (
          <div className="empty-state collection-empty-state">
            <strong>Коллекций пока нет</strong>
            <p>Создай первую — потом её можно будет выбрать при добавлении любой игры.</p>
            <button onClick={() => setCollectionCreatorOpen(true)}>Создать коллекцию</button>
          </div>
        )}

        <section className="collection-grid">
          {collections.map((collection) => {
            const items = entries
              .filter((entry) => entry.collectionIds.includes(collection.id))
              .map((entry) => catalogGames.find((game) => game.id === entry.gameId)!)
            return (
              <button className="collection-card" key={collection.id} onClick={() => setSelectedCollectionId(collection.id)}>
                <div className="collection-card__mosaic">
                  {items.slice(0, 4).map((game) => <Cover game={game} compact key={game.id} />)}
                  {items.length === 0 && <div className="collection-card__empty">{collection.mark}</div>}
                </div>
                <div className="collection-card__footer">
                  <div>
                    <strong>{collection.title}</strong>
                    <span>{items.length} {items.length === 1 ? 'игра' : 'игр'}</span>
                  </div>
                  <span className="collection-card__mark">{collection.mark}</span>
                </div>
              </button>
            )
          })}
        </section>
      </>
    )
  }

  const renderProfile = () => {
    const recent = entries
      .filter((entry) => entry.status === 'completed' && entry.completedAt)
      .sort((a, b) => (b.completedAt ?? '').localeCompare(a.completedAt ?? ''))
      .slice(0, 3)

    return (
      <>
        <div className="profile-back-row">
          <button className="profile-back" onClick={() => openTab('library')}>
            <Icon name="back" size={18} />
            <span>Мои игры</span>
          </button>
        </div>

        <section className="profile-hero">
          <div className="profile-avatar">{authUser?.nickname.slice(0, 1).toUpperCase()}</div>
          <span className="public-badge"><Icon name="globe" size={14} />Публичный профиль</span>
          <h1>@{authUser?.nickname}</h1>
          <p>rateapp / {authUser?.nickname}</p>
          <div className="profile-stats">
            <div><strong>{entries.length}</strong><span>игр</span></div>
            <div><strong>{counts.completed}</strong><span>пройдено</span></div>
            <div><strong>{collections.length}</strong><span>коллекции</span></div>
          </div>
        </section>

        <section className="info-card">
          <div className="section-heading section-heading--tight">
            <div>
              <span className="eyebrow">ПОСЛЕДНЕЕ</span>
              <h2>Недавно пройдено</h2>
            </div>
          </div>
          <div className="activity-list">
            {recent.map((entry) => {
              const game = catalogGames.find((item) => item.id === entry.gameId)!
              return (
                <button key={game.id} onClick={() => setSelectedGameId(game.id)}>
                  <span className="activity-cover"><Cover game={game} compact /></span>
                  <span><strong>{game.title}</strong><small>{formatDate(entry.completedAt)}</small></span>
                  <b>{entry.score?.toFixed(1)}</b>
                </button>
              )
            })}
          </div>
        </section>

        <section className="info-card account-card">
          <span className="eyebrow">АККАУНТ</span>
          <h2>Вход и восстановление</h2>
          <div className="account-row">
            <span><Icon name="mail" size={18} /><span><small>Email</small>{authUser?.email}</span></span>
            <button>Изменить</button>
          </div>
          <div className="account-row">
            <span><Icon name="lock" size={18} /><span><small>PIN-код</small>••••••</span></span>
            <button>Изменить</button>
          </div>
          <p className="privacy-note">Email и настройки входа видны только вам. Игровой профиль и коллекции публичные.</p>
          <button
            className="logout-button"
            onClick={async () => {
              await fetch('/api/auth/logout', { method: 'POST' })
              setAuthUser(null)
              setEntries([])
              setCollections([])
              setActiveTab('library')
            }}
          >
            Выйти из аккаунта
          </button>
        </section>
      </>
    )
  }

  const nav: { id: Tab; label: string; icon: IconName }[] = [
    { id: 'library', label: 'Мои игры', icon: 'gamepad' },
    { id: 'add', label: 'Добавить', icon: 'plus' },
    { id: 'collections', label: 'Коллекции', icon: 'layers' },
    { id: 'profile', label: 'Профиль', icon: 'user' },
  ]

  if (!authReady) {
    return (
      <div className="session-loading">
        <span className="session-loading__mark">R</span>
        <p>Загружаем RateApp…</p>
      </div>
    )
  }

  if (!authUser) {
    return <AuthScreen onAuthenticated={(user) => { void hydrateAfterLogin(user) }} />
  }

  return (
    <div className="app-shell">
      <main className="page">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={selectedGameId ? `detail-${selectedGameId}` : activeTab}
            className="page-motion"
            initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={shouldReduceMotion ? undefined : { opacity: 0, y: -6 }}
            transition={{ duration: .18, ease: [0.22, 1, 0.36, 1] }}
          >
            {selectedGameId ? renderDetail() : (
              <>
                {activeTab === 'library' && renderLibrary()}
                {activeTab === 'add' && renderAdd()}
                {activeTab === 'collections' && renderCollections()}
                {activeTab === 'profile' && renderProfile()}
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      {!selectedGameId && (
        <nav className="bottom-nav" aria-label="Основная навигация">
          {nav.map((item) => (
            <motion.button
              layout
              key={item.id}
              onClick={() => openTab(item.id)}
              className={activeTab === item.id ? 'bottom-nav__item bottom-nav__item--active' : 'bottom-nav__item'}
              whileTap={shouldReduceMotion ? undefined : { scale: .92 }}
              transition={{ type: 'spring', stiffness: 500, damping: 34 }}
            >
              {activeTab === item.id && (
                <motion.span
                  className="bottom-nav__active-surface"
                  layoutId="bottom-nav-active-surface"
                  transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                />
              )}
              <span className="bottom-nav__content">
                {item.id === 'profile' ? (
                  <span className="bottom-nav__avatar" aria-hidden="true">
                    {authUser.nickname.slice(0, 1).toUpperCase()}
                  </span>
                ) : (
                  <Icon name={item.icon} />
                )}
                <span>{item.label}</span>
              </span>
            </motion.button>
          ))}
        </nav>
      )}
    </div>
  )
}

export default App