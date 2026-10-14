import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  AnimatePresence,
  LayoutGroup,
  animate,
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useTransform,
} from 'motion/react'
import AuthScreen, { type AuthUser } from './AuthScreen'
import PushSettings, { PushOnboarding, disconnectPushForLogout } from './PushSettings'
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
  | 'edit'
  | 'trash'
  | 'sparkles'
  | 'book'
  | 'cpu'
  | 'clock'
  | 'video'

type Tab = 'library' | 'add' | 'collections' | 'profile'

type AppView = {
  tab: Tab
  gameId: number | null
  collectionId: string | null
  formGameId: number | null
}

type AppHistoryEntry = {
  rateAppView: true
  view: AppView
  scrollY: number
  fromApp: boolean
  controls?: {
    progress: number
    anchor: number
    forcedCollapsed: boolean
    topLatch: boolean
    entryAnchorActive: boolean
  }
}

const validTabs: Tab[] = ['library', 'add', 'collections', 'profile']

function readAppHistoryEntry(value: unknown): AppHistoryEntry | null {
  if (!value || typeof value !== 'object') return null
  const entry = value as Partial<AppHistoryEntry>
  if (entry.rateAppView !== true || !entry.view || !validTabs.includes(entry.view.tab)) return null
  return entry as AppHistoryEntry
}

function readAppViewFromUrl(): AppView {
  const params = new URLSearchParams(window.location.search)
  const tabName = params.get('tab') as Tab | null
  const tab: Tab = tabName && validTabs.includes(tabName) ? tabName : 'library'
  const gameId = Number(params.get('game'))
  const formGameId = Number(params.get('edit'))
  return {
    tab,
    gameId: Number.isSafeInteger(gameId) && gameId > 0 ? gameId : null,
    collectionId: tab === 'collections' ? params.get('collection') : null,
    formGameId: tab === 'add' && Number.isSafeInteger(formGameId) && formGameId > 0 ? formGameId : null,
  }
}

function urlForAppView(view: AppView): string {
  const url = new URL(window.location.href)
  for (const param of ['tab', 'game', 'collection', 'edit']) url.searchParams.delete(param)
  if (view.tab !== 'library') url.searchParams.set('tab', view.tab)
  if (view.gameId != null) url.searchParams.set('game', String(view.gameId))
  if (view.tab === 'collections' && view.collectionId) url.searchParams.set('collection', view.collectionId)
  if (view.tab === 'add' && view.formGameId != null) url.searchParams.set('edit', String(view.formGameId))
  return url.pathname + url.search + url.hash
}

function keyForAppView(view: AppView): string {
  if (view.gameId != null) return `detail-${view.gameId}`
  if (view.tab === 'collections' && view.collectionId) return `collection-${view.collectionId}`
  if (view.tab === 'add' && view.formGameId != null) return `add-game-${view.formGameId}`
  return view.tab
}

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

type GameSearchPage = {
  items: Game[]
  hasMore: boolean
  nextOffset: number | null
}

type SearchSource = 'local' | 'igdb'
const WISHLIST_COLLECTION_ID = 'wishlist'

// Wishlist-only records hold collection membership, not a playthrough.
const isPlaythrough = (entry?: LibraryEntry): entry is LibraryEntry =>
  Boolean(entry && entry.status !== 'wishlist')

// Apply membership optimistically while preserving all playthrough fields.
function withWishlistMembership(entries: LibraryEntry[], gameId: number, enabled: boolean): LibraryEntry[] {
  const entry = entries.find((item) => item.gameId === gameId)
  if (!entry) {
    if (!enabled) return entries
    return [...entries, {
      gameId,
      status: 'wishlist', // API placeholder, not a playthrough status.
      collectionIds: [WISHLIST_COLLECTION_ID],
      addedAt: new Date().toISOString().slice(0, 10),
    }]
  }

  const collectionIds = enabled
    ? Array.from(new Set([...entry.collectionIds, WISHLIST_COLLECTION_ID]))
    : entry.collectionIds.filter((id) => id !== WISHLIST_COLLECTION_ID)
  const others = entries.filter((item) => item.gameId !== gameId)
  return entry.status === 'wishlist' && collectionIds.length === 0
    ? others
    : [...others, { ...entry, collectionIds }]
}

type WishlistUpdate = { desired: boolean; persisted: boolean; syncing: boolean }

type GameStoreLink = {
  provider: string
  label: string
  url: string
}

type GameDetailExtras = {
  storyHours: number | null
  completionHours: number | null
  storeLinks: GameStoreLink[]
  trailerUrl: string | null
  game?: Game
}

const STORE_ICONS: Record<string, string> = {
  steam: '/brand/steam.svg',
  epic: '/brand/epicgames.svg',
  gog: '/brand/gogdotcom.svg',
  itch: '/brand/itchdotio.svg',
  playstation: '/brand/playstation.svg',
  xbox: '/brand/xbox.svg',
  nintendo: '/brand/nintendoswitch.svg',
  youtube: '/brand/youtube.svg',
}

function BrandIcon({ provider }: { provider: string }) {
  const iconUrl = STORE_ICONS[provider]
  return iconUrl
    ? <img className="detail-external-link__icon" src={iconUrl} alt="" aria-hidden="true" width={20} height={20} />
    : <Icon name="globe" size={20} />
}

function formatPlaytime(details?: GameDetailExtras, loading = false): string {
  if (loading && !details) return 'Загружаем…'
  const story = details?.storyHours
  const complete = details?.completionHours
  if (story != null && complete != null) {
    return story === complete ? `${story} ч` : `${story}–${complete} ч`
  }
  if (story != null) return `от ${story} ч`
  if (complete != null) return `до ${complete} ч`
  return '—'
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
  dropped: { label: 'Дропнуто', short: 'Дропнуто' },
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
    edit: <><path d="M12 20h9"/><path d="m16.5 4.5 3 3L8 19H5v-3L16.5 4.5Z"/><path d="m15 6 3 3"/></>,
    trash: <><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/><path d="M10 11v5M14 11v5"/></>,
    sparkles: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="m19 17 .7 1.3L21 19l-1.3.7L19 21l-.7-1.3L17 19l1.3-.7L19 17Z"/></>,
    book: <><path d="M12 6c-2.3-1.6-5.3-1.9-9-1v14c3.7-.9 6.7-.6 9 1 2.3-1.6 5.3-1.9 9-1V5c-3.7-.9-6.7-.6-9 1Z"/><path d="M12 6v14"/></>,
    cpu: <><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></>,
    video: <><rect x="2.5" y="5.5" width="19" height="13" rx="4"/><path d="m10 9 5 3-5 3V9Z"/></>,
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
  thumbnail = false,
  priority = false,
}: {
  game: Game
  compact?: boolean
  markers?: GameCollection[]
  thumbnail?: boolean
  priority?: boolean
}) {
  const imageUrl = thumbnail
    ? game.coverUrl?.replace('/t_cover_big_2x/', '/t_cover_small/')
    : game.coverUrl
  const style = {
    '--cover-accent': game.accent,
    '--cover-accent-2': game.accent2,
  } as CSSProperties

  return (
    <div className={compact ? 'cover cover--compact' : 'cover'} style={style}>
      {imageUrl && (
        <img
          className="cover__image"
          src={imageUrl}
          alt=""
          loading={priority ? 'eager' : 'lazy'}
          fetchPriority={priority ? 'high' : undefined}
          decoding="async"
        />
      )}
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

type GameCardProps = {
  game: Game
  entry: LibraryEntry
  collections: GameCollection[]
  onOpen: () => void
  animationIndex?: number
}

const GameCard = forwardRef<HTMLButtonElement, GameCardProps>(function GameCard({
  game,
  entry,
  collections,
  onOpen,
  animationIndex = 0,
}, ref) {
  const shouldReduceMotion = useReducedMotion()
  void animationIndex
  const markers = collections.filter((collection) => entry.collectionIds.includes(collection.id))
  const activityDate =
    entry.status === 'completed' && entry.completedAt
      ? entry.completedAt
      : entry.status === 'playing' && entry.startedAt
        ? entry.startedAt
        : entry.addedAt

  return (
    <motion.button
      ref={ref}
      layout="position"
      className="game-card"
      onClick={onOpen}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 16, scale: .985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={shouldReduceMotion ? undefined : { opacity: 0, scale: .975 }}
      whileTap={shouldReduceMotion ? undefined : { scale: .985 }}
      transition={{
        layout: { type: 'spring', stiffness: 430, damping: 34, mass: .72 },
        opacity: { duration: .16 },
        scale: { type: 'spring', stiffness: 430, damping: 34, mass: .72 },
        y: { type: 'spring', stiffness: 430, damping: 34, mass: .72 },
      }}
    >
      <div className="game-card__cover-wrap">
        <Cover game={game} markers={markers} />
        {entry.score != null && (
          <span className="score-badge">{entry.score.toFixed(1)}</span>
        )}
        {isPlaythrough(entry) && (
          <span className={`status-badge status-badge--${entry.status}`}>
            <Icon name={statusIcons[entry.status]} size={12} />
            <span className="status-badge__label">{statusMeta[entry.status].short}</span>
            <span className="status-badge__date">{formatCardDate(activityDate)}</span>
          </span>
        )}
      </div>
      <div className="game-card__body">
        <h3>{game.title}</h3>
      </div>
    </motion.button>
  )
})

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
  const firstViewRef = useRef<AppView | null>(null)
  if (!firstViewRef.current) {
    firstViewRef.current = readAppHistoryEntry(window.history.state)?.view ?? readAppViewFromUrl()
  }
  const [activeTab, setActiveTab] = useState<Tab>(firstViewRef.current.tab)
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [entries, setEntries] = useState<LibraryEntry[]>([])
  const [collections, setCollections] = useState<GameCollection[]>([])
  const [catalogGames, setCatalogGames] = useState<Game[]>(games)
  const [addResults, setAddResults] = useState<Game[]>([])
  const [addSearchLoading, setAddSearchLoading] = useState(false)
  const [addSearchError, setAddSearchError] = useState('')
  const [addSearchSource, setAddSearchSource] = useState<SearchSource>('local')
  const [localSearchMissQuery, setLocalSearchMissQuery] = useState<string | null>(null)
  const [addSearchHasMore, setAddSearchHasMore] = useState(false)
  const [addSearchNextOffset, setAddSearchNextOffset] = useState(0)
  const addSearchGenerationRef = useRef(0)
  const addSearchAbortRef = useRef<AbortController | null>(null)
  const addSearchBusyRef = useRef(false)
  const addSearchSentinelRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [statusFilters, setStatusFilters] = useState<LibraryStatus[]>([])
  const [genreFilter, setGenreFilter] = useState('all')
  const [platformFilter, setPlatformFilter] = useState('all')
  const [sortMode, setSortMode] = useState<SortMode>('activity')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [librarySearchOpen, setLibrarySearchOpen] = useState(false)
  const librarySearchInputRef = useRef<HTMLInputElement>(null)
  const focusLibrarySearchOnOpen = useRef(false)
  const [libraryControlsCollapsed, setLibraryControlsCollapsed] = useState(false)
  const [libraryControlsMeasured, setLibraryControlsMeasured] = useState(false)
  const libraryControlsObserverRef = useRef<ResizeObserver | null>(null)
  const libraryControlsMeasureFrameRef = useRef<number | null>(null)
  const libraryToggleAnimationRef = useRef<{ stop: () => void } | null>(null)
  const libraryToggleGenerationRef = useRef(0)
  const libraryEntryAnchorActiveRef = useRef(false)
  const libraryHasOpenedRef = useRef(false)
  const libraryCollapseProgress = useMotionValue(0)
  const libraryMeasuredControlsHeight = useMotionValue(0)
  const libraryControlClipHeight = useTransform(
    () => libraryMeasuredControlsHeight.get() * (1 - libraryCollapseProgress.get()),
  )
  const libraryControlClipOpacity = useTransform(
    () => Math.max(0, 1 - libraryCollapseProgress.get() * 1.18),
  )
  const libraryScrollAnchorRef = useRef(0)
  const libraryForceCollapsedRef = useRef(false)
  const libraryScrollSyncPausedRef = useRef(false)
  const libraryLastScrollYRef = useRef(0)
  const libraryTopLatchRef = useRef(false)
  const libraryForcedRevealStartRef = useRef<number | null>(null)
  const [selectedGameId, setSelectedGameId] = useState<number | null>(firstViewRef.current.gameId)
  const wishlistUpdatesRef = useRef(new Map<number, WishlistUpdate>())
  const [gameDetailsById, setGameDetailsById] = useState<Record<number, GameDetailExtras>>({})
  const [loadingGameDetailsId, setLoadingGameDetailsId] = useState<number | null>(null)
  const [failedGameDetailsId, setFailedGameDetailsId] = useState<number | null>(null)
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(firstViewRef.current.collectionId)
  const currentViewRef = useRef<AppView>(firstViewRef.current)
  const pendingScreenRestoreRef = useRef<AppHistoryEntry | null>(null)
  const libraryLastSnapshotRef = useRef<AppHistoryEntry | null>(null)
  const [collectionCreatorOpen, setCollectionCreatorOpen] = useState(false)
  const [collectionTitle, setCollectionTitle] = useState('')
  const [collectionDescription, setCollectionDescription] = useState('')
  const [collectionMark, setCollectionMark] = useState('')
  const [collectionSaving, setCollectionSaving] = useState(false)
  const [collectionError, setCollectionError] = useState('')

  const [addQuery, setAddQuery] = useState('')
  const [addGameId, setAddGameId] = useState<number | null>(firstViewRef.current.formGameId)
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

  useMotionValueEvent(libraryCollapseProgress, 'change', (latest) => {
    const collapsed = latest >= 0.84
    setLibraryControlsCollapsed((current) => current === collapsed ? current : collapsed)
  })

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

  const captureCurrentView = () => {
    const view = currentViewRef.current
    const existing = readAppHistoryEntry(window.history.state)
    const snapshot: AppHistoryEntry = {
      rateAppView: true,
      view,
      fromApp: existing?.fromApp ?? false,
      scrollY: Math.max(0, window.scrollY),
    }

    if (view.tab === 'library' && view.gameId == null) {
      snapshot.controls = {
        progress: libraryCollapseProgress.get(),
        anchor: libraryScrollAnchorRef.current,
        forcedCollapsed: libraryForceCollapsedRef.current,
        topLatch: libraryTopLatchRef.current,
        entryAnchorActive: libraryEntryAnchorActiveRef.current,
      }
      libraryLastSnapshotRef.current = snapshot
    }

    window.history.replaceState(snapshot, '', urlForAppView(view))
  }

  const showAppView = (view: AppView, restoredEntry: AppHistoryEntry) => {
    currentViewRef.current = view
    pendingScreenRestoreRef.current = restoredEntry
    if (view.tab === 'library' && view.gameId == null) {
      // Do not let scroll callbacks overwrite the saved collapsed state
      // before the library's animated screen has actually remounted.
      libraryScrollSyncPausedRef.current = true
      libraryCollapseProgress.set(restoredEntry.controls?.progress ?? 0)
    }
    setActiveTab(view.tab)
    setSelectedGameId(view.gameId)
    setSelectedCollectionId(view.collectionId)
    setAddGameId(view.formGameId)
  }

  const navigateTo = (view: AppView, options?: { replace?: boolean; restoreLibrary?: boolean }) => {
    if (keyForAppView(currentViewRef.current) === keyForAppView(view)) return

    captureCurrentView()
    const savedLibrary = options?.restoreLibrary ? libraryLastSnapshotRef.current : null
    const entry: AppHistoryEntry = {
      rateAppView: true,
      view,
      scrollY: savedLibrary?.scrollY ?? 0,
      fromApp: options?.replace
        ? (readAppHistoryEntry(window.history.state)?.fromApp ?? false)
        : true,
      controls: savedLibrary?.controls,
    }
    if (options?.replace) window.history.replaceState(entry, '', urlForAppView(view))
    else window.history.pushState(entry, '', urlForAppView(view))
    showAppView(view, entry)
  }

  const goBackOr = (fallback: AppView) => {
    if (readAppHistoryEntry(window.history.state)?.fromApp) {
      captureCurrentView()
      window.history.back()
    } else {
      navigateTo(fallback, { replace: true, restoreLibrary: fallback.tab === 'library' && fallback.gameId == null })
    }
  }

  // Browser history is the source of truth for Android's system Back action
  // and Safari's native edge-swipe navigation, including browser Forward.
  useEffect(() => {
    const previousRestoration = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    const previous = readAppHistoryEntry(window.history.state)
    const initial = currentViewRef.current
    window.history.replaceState(
      previous ?? { rateAppView: true, view: initial, scrollY: 0, fromApp: false },
      '',
      urlForAppView(initial),
    )

    const onPopState = (event: PopStateEvent) => {
      const entry = readAppHistoryEntry(event.state) ?? {
        rateAppView: true as const,
        view: readAppViewFromUrl(),
        scrollY: 0,
        fromApp: false,
      }
      showAppView(entry.view, entry)
    }

    window.addEventListener('popstate', onPopState)
    return () => {
      window.removeEventListener('popstate', onPopState)
      window.history.scrollRestoration = previousRestoration
    }
  }, [])

  const restoreScreenPosition = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const saved = pendingScreenRestoreRef.current
    if (!saved || keyForAppView(saved.view) !== keyForAppView(currentViewRef.current)) return

    // AnimatePresence(mode="wait") delays mounting the destination page.
    // Restore only after it exists and its list has laid out.
    window.requestAnimationFrame(() => {
      if (pendingScreenRestoreRef.current !== saved) return
      if (saved.view.tab === 'library' && saved.view.gameId == null) {
        libraryCollapseProgress.set(saved.controls?.progress ?? 0)
      }
      window.scrollTo(0, saved.scrollY)
      window.requestAnimationFrame(() => {
        if (pendingScreenRestoreRef.current !== saved) return
        window.scrollTo(0, saved.scrollY)
        libraryLastScrollYRef.current = Math.max(0, window.scrollY)
        pendingScreenRestoreRef.current = null
        libraryScrollSyncPausedRef.current = false
      })
    })
  }, [libraryCollapseProgress])

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

  useEffect(() => {
    // The App renders a loading/auth shell before the library mounts.
    // Never read or apply its scroll position as library collapse progress.
    if (!authReady || !authUser || activeTab !== 'library' || selectedGameId != null) return

    const collapseDistance = 210
    const topStart = 4
    let scrollFrame: number | null = null

    const pending = pendingScreenRestoreRef.current
    const restoringLibrary = pending?.view.tab === 'library' && pending.view.gameId == null
    const savedControls = restoringLibrary ? pending.controls : undefined

    // Only the very first, non-restored library visit starts at scroll zero.
    // A Back navigation instead restores the snapshot from browser history.
    if (!libraryHasOpenedRef.current) {
      libraryHasOpenedRef.current = true
      if (!restoringLibrary && window.scrollY !== 0) window.scrollTo(0, 0)
    }

    libraryToggleGenerationRef.current += 1
    libraryToggleAnimationRef.current?.stop()
    libraryToggleAnimationRef.current = null
    libraryScrollSyncPausedRef.current = Boolean(restoringLibrary)
    const progress = savedControls?.progress ?? 0
    libraryCollapseProgress.set(progress)
    setLibraryControlsCollapsed(progress >= .84)

    const initialY = restoringLibrary && pending
      ? Math.max(0, pending.scrollY)
      : Math.max(0, window.scrollY)
    libraryScrollAnchorRef.current = savedControls?.anchor ?? Math.max(topStart, initialY)
    libraryEntryAnchorActiveRef.current = savedControls?.entryAnchorActive ?? initialY > topStart
    libraryForceCollapsedRef.current = savedControls?.forcedCollapsed ?? false
    libraryForcedRevealStartRef.current = null
    libraryTopLatchRef.current = savedControls?.topLatch ?? initialY <= topStart
    libraryLastScrollYRef.current = initialY

    const syncControlsToScroll = () => {
      if (libraryScrollSyncPausedRef.current) return

      const currentY = Math.max(0, window.scrollY)
      const previousY = libraryLastScrollYRef.current
      const scrollingDown = currentY > previousY + .5
      libraryLastScrollYRef.current = currentY

      // Keep the library open through the native top-of-page rubber band.
      if (currentY <= topStart) {
        libraryTopLatchRef.current = true
        libraryEntryAnchorActiveRef.current = false
        libraryScrollAnchorRef.current = topStart
        libraryForceCollapsedRef.current = false
        libraryCollapseProgress.set(0)
        return
      }

      if (libraryTopLatchRef.current) {
        if (!scrollingDown || currentY < topStart + 18) {
          libraryCollapseProgress.set(0)
          return
        }
        libraryTopLatchRef.current = false
      }

      if (libraryForceCollapsedRef.current) {
        libraryCollapseProgress.set(1)
        return
      }

      // When returning from details, the browser may restore a nonzero
      // scroll offset. Start expanded and animate from that entry offset,
      // instead of instantly jumping to the global top-zone progress.
      if (libraryEntryAnchorActiveRef.current) {
        const progress = Math.min(1, Math.max(
          0,
          (currentY - libraryScrollAnchorRef.current) / collapseDistance,
        ))
        libraryCollapseProgress.set(progress)
        return
      }

      // The top 210px is a symmetric collapse/reveal zone.
      if (currentY <= topStart + collapseDistance) {
        libraryCollapseProgress.set(Math.min(1, Math.max(0, (currentY - topStart) / collapseDistance)))
        return
      }

      const anchor = libraryScrollAnchorRef.current || topStart
      libraryCollapseProgress.set(Math.min(1, Math.max(0, (currentY - anchor) / collapseDistance)))
    }

    const queueScrollSync = () => {
      if (scrollFrame != null) return
      scrollFrame = window.requestAnimationFrame(() => {
        scrollFrame = null
        syncControlsToScroll()
      })
    }

    // Do not sync immediately: the incoming library hasn't measured or
    // mounted during the AnimatePresence route transition.
    window.addEventListener('scroll', queueScrollSync, { passive: true })
    return () => {
      window.removeEventListener('scroll', queueScrollSync)
      if (scrollFrame != null) window.cancelAnimationFrame(scrollFrame)
      libraryToggleGenerationRef.current += 1
      libraryToggleAnimationRef.current?.stop()
      libraryToggleAnimationRef.current = null
      libraryScrollSyncPausedRef.current = false
    }
  }, [authReady, authUser, activeTab, selectedGameId, libraryCollapseProgress])

  // The library page is unmounted while a game detail is visible. Measuring
  // only in an App-level effect misses its delayed remount (AnimatePresence
  // mode="wait"), leaving the animated clip with a height of zero.
  const measureLibraryControls = useCallback((node: HTMLDivElement | null) => {
    libraryControlsObserverRef.current?.disconnect()
    libraryControlsObserverRef.current = null

    if (libraryControlsMeasureFrameRef.current !== null) {
      window.cancelAnimationFrame(libraryControlsMeasureFrameRef.current)
      libraryControlsMeasureFrameRef.current = null
    }

    if (!node) return

    const updateHeight = () => {
      if (!node.isConnected) return
      const height = node.getBoundingClientRect().height
      if (height <= 0 || !Number.isFinite(height)) return

      libraryMeasuredControlsHeight.set(height)
      setLibraryControlsMeasured(true)
    }

    updateHeight()
    const observer = new ResizeObserver(updateHeight)
    observer.observe(node)
    libraryControlsObserverRef.current = observer

    // Measure once more after Motion attaches its subscriptions and the
    // library entrance transition has committed.
    libraryControlsMeasureFrameRef.current = window.requestAnimationFrame(() => {
      libraryControlsMeasureFrameRef.current = null
      updateHeight()
    })
  }, [libraryMeasuredControlsHeight])

  const entryMap = useMemo(
    () => new Map(entries.map((entry) => [entry.gameId, entry])),
    [entries],
  )

  // A wishlist-only record belongs to «Хочу пройти», not to «Мои игры».
  // Keep it in entries so collection membership, detail actions and release
  // notifications continue to work as before.
  const personalLibraryEntries = useMemo(
    () => entries.filter((entry) => entry.status !== 'wishlist'),
    [entries],
  )

  const availableGenres = useMemo(() => {
    const libraryGameIds = new Set(personalLibraryEntries.map((entry) => entry.gameId))
    return Array.from(
      new Set(
        catalogGames
          .filter((game) => libraryGameIds.has(game.id))
          .flatMap((game) => game.genres),
      ),
    ).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [personalLibraryEntries, catalogGames])

  const availablePlatforms = useMemo(() => {
    return Array.from(
      new Set(personalLibraryEntries.map((entry) => entry.platform).filter((platform): platform is string => Boolean(platform))),
    ).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [personalLibraryEntries])

  const libraryGames = useMemo(() => {
    const normalized = query.trim().toLowerCase()

    const result = personalLibraryEntries
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
  }, [personalLibraryEntries, query, statusFilters, genreFilter, platformFilter, sortMode, catalogGames])

  const activeExtraFilters =
    (genreFilter !== 'all' ? 1 : 0) +
    (platformFilter !== 'all' ? 1 : 0)

  const resetExtraFilters = () => {
    setGenreFilter('all')
    setPlatformFilter('all')
  }

  const rememberCatalogResults = useCallback((results: Game[]) => {
    if (results.length === 0) return
    setCatalogGames((current) => {
      const merged = new Map(current.map((game) => [game.id, game]))
      results.forEach((game) => merged.set(game.id, game))
      return Array.from(merged.values())
    })
  }, [])

  const loadSearchPage = useCallback(async ({
    query,
    source,
    offset,
    append,
    generation,
  }: {
    query: string
    source: SearchSource
    offset: number
    append: boolean
    generation: number
  }) => {
    if (addSearchBusyRef.current || generation !== addSearchGenerationRef.current) return

    const controller = new AbortController()
    addSearchAbortRef.current = controller
    addSearchBusyRef.current = true
    setAddSearchLoading(true)
    setAddSearchError('')

    try {
      const params = new URLSearchParams({
        q: query,
        source,
        offset: String(offset),
      })
      const response = await fetch(`/api/games/search?${params}`, {
        signal: controller.signal,
      })
      const payload = await response.json().catch(() => null) as GameSearchPage | { detail?: string } | null
      if (controller.signal.aborted || generation !== addSearchGenerationRef.current) return

      if (!response.ok || !payload || !('items' in payload) || !Array.isArray(payload.items)) {
        const detail = payload && 'detail' in payload ? payload.detail : undefined
        throw new Error(detail || (source === 'igdb'
          ? 'Не удалось загрузить игры из IGDB.'
          : 'Не удалось выполнить поиск в базе игр.'))
      }

      const page = payload as GameSearchPage
      setAddResults((current) => {
        if (!append) return page.items
        const known = new Set(current.map((game) => game.id))
        return [...current, ...page.items.filter((game) => {
          if (known.has(game.id)) return false
          known.add(game.id)
          return true
        })]
      })
      setAddSearchHasMore(Boolean(page.hasMore))
      setAddSearchNextOffset(page.nextOffset ?? offset + page.items.length)
      if (source === 'local' && !append && page.items.length === 0) {
        // IGDB includes uncached games, including announced future releases.
        setLocalSearchMissQuery(query)
      }
      rememberCatalogResults(page.items)
    } catch (error) {
      if (!controller.signal.aborted && generation === addSearchGenerationRef.current) {
        setAddSearchError(
          error instanceof Error ? error.message : 'Не удалось загрузить игры. Попробуй снова.',
        )
      }
    } finally {
      if (generation === addSearchGenerationRef.current) {
        addSearchBusyRef.current = false
        if (addSearchAbortRef.current === controller) addSearchAbortRef.current = null
        setAddSearchLoading(false)
      }
    }
  }, [rememberCatalogResults])

  useEffect(() => {
    const query = addQuery.trim()
    const generation = ++addSearchGenerationRef.current
    addSearchAbortRef.current?.abort()
    addSearchAbortRef.current = null
    addSearchBusyRef.current = false

    setAddSearchSource('local')
    setLocalSearchMissQuery(null)
    setAddResults([])
    setAddSearchError('')
    setAddSearchHasMore(false)
    setAddSearchNextOffset(0)
    setAddSearchLoading(query.length >= 3)

    if (query.length < 3) return

    const timer = window.setTimeout(() => {
      void loadSearchPage({ query, source: 'local', offset: 0, append: false, generation })
    }, 350)

    return () => {
      window.clearTimeout(timer)
      addSearchAbortRef.current?.abort()
      addSearchBusyRef.current = false
    }
  }, [addQuery, loadSearchPage])

  useEffect(() => {
    if (
      activeTab !== 'add' ||
      addGameId != null ||
      selectedGameId != null ||
      !addSearchHasMore ||
      addSearchLoading ||
      addSearchError ||
      addQuery.trim().length < 3
    ) return

    const sentinel = addSearchSentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting || addSearchBusyRef.current) return
      void loadSearchPage({
        query: addQuery.trim(),
        source: addSearchSource,
        offset: addSearchNextOffset,
        append: true,
        generation: addSearchGenerationRef.current,
      })
    }, { rootMargin: '600px 0px', threshold: 0 })

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [
    activeTab, addGameId, selectedGameId, addSearchHasMore,
    addSearchLoading, addSearchError, addSearchSource,
    addSearchNextOffset, addQuery, addResults.length, loadSearchPage,
  ])

  const searchIgdb = () => {
    const query = addQuery.trim()
    if (
      query.length < 3 ||
      addSearchLoading ||
      addSearchBusyRef.current ||
      addSearchSource === 'igdb'
    ) return

    const generation = ++addSearchGenerationRef.current
    setAddSearchSource('igdb')
    setAddResults([])
    setAddSearchHasMore(false)
    setAddSearchNextOffset(0)
    // IGDB is a new result stream: starting at page one avoids repeated
    // local/IGDB matches and an auto-loading loop when both contain the
    // same games. The list is still infinite-scroll in either mode.
    window.scrollTo({ top: 0, behavior: 'instant' })
    void loadSearchPage({ query, source: 'igdb', offset: 0, append: false, generation })
  }

  useEffect(() => {
    const currentQuery = addQuery.trim()
    if (
      !localSearchMissQuery ||
      localSearchMissQuery !== currentQuery ||
      addSearchSource !== 'local' ||
      addSearchLoading ||
      addSearchBusyRef.current
    ) return

    // Empty local results should seamlessly search IGDB without making the
    // user guess that a separate database search is required.
    setLocalSearchMissQuery(null)
    searchIgdb()
  }, [localSearchMissQuery, addQuery, addSearchSource, addSearchLoading])

  const retrySearch = () => {
    if (addSearchBusyRef.current) return
    void loadSearchPage({
      query: addQuery.trim(),
      source: addSearchSource,
      offset: addSearchNextOffset,
      append: addSearchSource === 'igdb' || addSearchNextOffset > 0,
      generation: addSearchGenerationRef.current,
    })
  }

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
    navigateTo({ tab, gameId: null, collectionId: null, formGameId: null })
  }

  const openGame = (gameId: number) => {
    navigateTo({
      tab: currentViewRef.current.tab,
      gameId,
      collectionId: currentViewRef.current.collectionId,
      formGameId: null,
    })
  }

  const editingFromDetailRef = useRef(false)

  const startAdding = (game: Game) => {
    editingFromDetailRef.current = false
    setAddStatus('completed')
    setAddPlatform(preferredPlatform(game.platforms))
    setAddDate(new Date().toISOString().slice(0, 10))
    setAddAtmosphereScore(8)
    setAddStoryScore(8)
    setAddTechnologyScore(8)
    setAddGameplayScore(8)
    setAddReview('')
    setAddReviewOpen(false)
    // Preserve memberships when a wishlist-only game gains a playthrough.
    setAddCollectionIds(entryMap.get(game.id)?.collectionIds ?? [])
    navigateTo({ tab: 'add', gameId: null, collectionId: null, formGameId: game.id })
  }

  const startEditing = (game: Game, entry: LibraryEntry) => {
    editingFromDetailRef.current = currentViewRef.current.gameId === game.id
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
    navigateTo({ tab: 'add', gameId: null, collectionId: null, formGameId: game.id })
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

      if (!response.ok) {
        window.alert('Не удалось сохранить игру. Попробуйте ещё раз.')
        return
      }
      const savedPayload = await response.json() as ApiLibraryEntry
      const savedEntry = normalizeEntry(savedPayload)
      setEntries((current) => [...current.filter((entry) => entry.gameId !== game.id), savedEntry])
      if (savedPayload.game) rememberCatalogResults([savedPayload.game])
    } catch {
      window.alert('Не удалось сохранить игру. Проверьте соединение и попробуйте ещё раз.')
      return
    }

    setAddQuery('')
    const gameView: AppView = { tab: 'library', gameId: game.id, collectionId: null, formGameId: null }
    if (editingFromDetailRef.current) {
      editingFromDetailRef.current = false
      goBackOr(gameView)
    } else {
      navigateTo(gameView, { replace: true })
    }
  }

  const syncWishlist = async (gameId: number, update: WishlistUpdate) => {
    if (update.syncing) return
    update.syncing = true
    try {
      // Serialize requests per game so fast repeated taps cannot race on the server.
      while (update.desired !== update.persisted) {
        const next = update.desired
        const response = await fetch(`/api/library/${gameId}/wishlist`, {
          method: next ? 'PUT' : 'DELETE',
        })
        if (!response.ok) throw new Error('Wishlist update failed')
        update.persisted = next
      }
    } catch {
      // Restore the last confirmed state only if persistence fails.
      setEntries((current) => withWishlistMembership(current, gameId, update.persisted))
      window.alert('Не удалось обновить список «Хочу пройти». Попробуйте ещё раз.')
    } finally {
      wishlistUpdatesRef.current.delete(gameId)
      update.syncing = false
    }
  }

  const toggleWishlist = (game: Game) => {
    let update = wishlistUpdatesRef.current.get(game.id)
    const inWishlist = update?.desired ?? Boolean(
      entryMap.get(game.id)?.collectionIds.includes(WISHLIST_COLLECTION_ID),
    )
    if (!update) {
      update = { desired: !inWishlist, persisted: inWishlist, syncing: false }
      wishlistUpdatesRef.current.set(game.id, update)
    } else {
      update.desired = !inWishlist
    }

    // Update the interface immediately; persist in the background.
    setEntries((current) => withWishlistMembership(current, game.id, !inWishlist))
    void syncWishlist(game.id, update)
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
      if (currentViewRef.current.gameId === game.id) {
        goBackOr({ tab: 'library', gameId: null, collectionId: null, formGameId: null })
      } else {
        navigateTo({ tab: 'library', gameId: null, collectionId: null, formGameId: null }, { replace: true, restoreLibrary: true })
      }
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
      navigateTo({ tab: 'collections', gameId: null, collectionId: payload.id, formGameId: null })
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

  // IGDB metadata is fetched only when the detail screen opens; search
  // results remain fast. The API caches enriched data for future opens.
  useEffect(() => {
    const gameId = selectedGameId
    if (
      !authUser ||
      gameId == null ||
      gameDetailsById[gameId] ||
      failedGameDetailsId === gameId
    ) return

    const controller = new AbortController()
    setLoadingGameDetailsId(gameId)

    const fetchDetails = async () => {
      try {
        const response = await fetch(`/api/games/${gameId}/details`, {
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Game metadata is not available')
        const payload = await response.json() as GameDetailExtras
        if (controller.signal.aborted) return
        if (payload.game) rememberCatalogResults([payload.game])
        setGameDetailsById((previous) => ({ ...previous, [gameId]: {
          storyHours: typeof payload.storyHours === 'number' ? payload.storyHours : null,
          completionHours: typeof payload.completionHours === 'number' ? payload.completionHours : null,
          storeLinks: Array.isArray(payload.storeLinks) ? payload.storeLinks : [],
          trailerUrl: typeof payload.trailerUrl === 'string' ? payload.trailerUrl : null,
        } }))
      } catch (error) {
        if (!controller.signal.aborted) setFailedGameDetailsId(gameId)
      } finally {
        if (!controller.signal.aborted) {
          setLoadingGameDetailsId((current) => current === gameId ? null : current)
        }
      }
    }

    void fetchDetails()
    return () => controller.abort()
  }, [authUser, selectedGameId, gameDetailsById, failedGameDetailsId, rememberCatalogResults])

  const selectedEntry = selectedGameId ? entryMap.get(selectedGameId) : undefined
  const selectedGame = selectedGameId ? catalogGames.find((game) => game.id === selectedGameId) : undefined

  const renderDetail = () => {
    if (!selectedGame) {
      return (
        <div className="detail-page">
          <div className="detail-toolbar">
            <button
              className="icon-button detail-back"
              onClick={() => goBackOr({ tab: 'library', gameId: null, collectionId: null, formGameId: null })}
              aria-label="Назад"
            >
              <Icon name="back" size={20} />
            </button>
          </div>
          <p className="game-database-loading" role="status">
            {failedGameDetailsId === selectedGameId ? 'Не удалось загрузить игру.' : 'Загружаем игру из базы…'}
          </p>
        </div>
      )
    }
    const gameCollections = selectedEntry
      ? collections.filter((collection) => selectedEntry.collectionIds.includes(collection.id))
      : []
    // A game already being played or completed does not need a wish action,
    // regardless of which collections it belongs to.
    const canWish = selectedEntry?.status !== 'completed' && selectedEntry?.status !== 'playing'
    const isWished = Boolean(selectedEntry?.collectionIds.includes(WISHLIST_COLLECTION_ID))
    const rateAppScore = selectedGame.communityRatings > 0
      ? selectedGame.communityRating.toFixed(1)
      : '—'
    const igdbScore = selectedGame.igdbRating > 0
      ? String(selectedGame.igdbRating)
      : '—'
    const gameDetails = gameDetailsById[selectedGame.id]
    const loadingDetails = loadingGameDetailsId === selectedGame.id

    return (
      <div className="detail-page">
        <div className="detail-toolbar">
          <button
            className="icon-button detail-back"
            onClick={() => goBackOr({
              tab: currentViewRef.current.tab,
              gameId: null,
              collectionId: currentViewRef.current.collectionId,
              formGameId: null,
            })}
            aria-label="Вернуться назад"
            title="Назад"
          >
            <Icon name="back" size={20} />
          </button>
          <div className="detail-toolbar__actions">
            {canWish && (
              <motion.button
                type="button"
                className={`detail-catalog-icon detail-catalog-icon--wish${isWished ? ' detail-catalog-icon--wish-active' : ''}`}
                onClick={() => { void toggleWishlist(selectedGame) }}
                aria-pressed={isWished}
                aria-label={isWished ? 'Убрать из коллекции «Хочу пройти»' : 'Хочу пройти — добавить в коллекцию'}
                title={isWished ? 'В «Хочу пройти» — нажми, чтобы убрать' : 'Добавить в «Хочу пройти»'}
                whileTap={shouldReduceMotion ? undefined : { scale: .92 }}
                transition={{ type: 'spring', stiffness: 460, damping: 27 }}
              >
                <motion.span
                  key={isWished ? 'wished' : 'not-wished'}
                  className="detail-catalog-icon__glyph"
                  initial={shouldReduceMotion ? false : { opacity: .55, scale: .72, rotate: -12 }}
                  animate={{ opacity: 1, scale: 1, rotate: 0 }}
                  transition={{ type: 'spring', stiffness: 520, damping: 28 }}
                >
                  <Icon name="bookmark" size={19} />
                </motion.span>
              </motion.button>
            )}
            {isPlaythrough(selectedEntry) ? (
              <>
                <button
                  className="icon-button detail-edit"
                  onClick={() => startEditing(selectedGame, selectedEntry)}
                  aria-label="Редактировать запись об игре"
                  title="Редактировать"
                >
                  <Icon name="edit" size={19} />
                </button>
                <button
                  className="icon-button detail-delete"
                  onClick={() => { void deleteGame(selectedGame) }}
                  aria-label="Удалить игру из моей библиотеки"
                  title="Удалить"
                >
                  <Icon name="trash" size={19} />
                </button>
              </>
            ) : (
              <button
                type="button"
                className="detail-catalog-icon detail-catalog-icon--add"
                onClick={() => startAdding(selectedGame)}
                aria-label="Добавить игру в библиотеку"
                title="Добавить игру"
              >
                <Icon name="plus" size={20} />
              </button>
            )}
          </div>
        </div>

        <section className="detail-hero">
          <div className={selectedGame.coverUrl ? 'detail-hero__cover detail-hero__cover--image' : 'detail-hero__cover'}>
            <Cover game={selectedGame} markers={gameCollections.filter((collection) => collection.id !== WISHLIST_COLLECTION_ID)} priority />
          </div>
          <div className="detail-hero__info">
            <h1>{selectedGame.title}</h1>
            <div className="detail-hero__metadata">
              <p className="detail-hero__genres">{selectedGame.genres.join(' · ') || 'Жанр не указан'}</p>
            </div>
            <div className="detail-external-links" aria-label="Ссылки на магазины и трейлер">
              {gameDetails?.storeLinks.map((store) => (
                <a
                  key={store.provider}
                  className={`detail-external-link detail-external-link--${store.provider}`}
                  href={store.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={store.label}
                  aria-label={`Открыть ${store.label}`}
                >
                  <BrandIcon provider={store.provider} />
                </a>
              ))}
              {gameDetails?.trailerUrl && (
                <a
                  className="detail-external-link detail-external-link--trailer"
                  href={gameDetails.trailerUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Смотреть трейлер"
                  aria-label="Смотреть трейлер на YouTube"
                >
                  <BrandIcon provider="youtube" />
                </a>
              )}
              {loadingDetails && !gameDetails && (
                <span className="detail-external-links__loading" aria-label="Загружаем ссылки" />
              )}
              {!loadingDetails && !gameDetails?.storeLinks.length && !gameDetails?.trailerUrl && (
                <span className="detail-external-links__empty">Ссылок пока нет</span>
              )}
            </div>
          </div>
        </section>

        <section className="detail-rating-section" aria-label="Рейтинги игры">
          <div className="detail-rating-panel detail-rating-panel--igdb" aria-label={`IGDB: ${igdbScore} из 100`}>
            <span className="detail-rating-panel__label">IGDB</span>
            <span className="detail-rating-panel__score">
              <strong>{igdbScore}</strong>
              <small>/ 100</small>
            </span>
          </div>
          <div className="detail-rating-panel detail-rating-panel--community" aria-label={`RateApp: ${rateAppScore} из 10`}>
            <span className="detail-rating-panel__label">RateApp</span>
            <span className="detail-rating-panel__score">
              <strong>{rateAppScore}</strong>
              <small>/ 10</small>
            </span>
          </div>
        </section>

        {selectedEntry && ratedStatuses.has(selectedEntry.status) && (
          <section className="criteria-card">
            <div className="criteria-card__header">
              <span className="eyebrow">МОЯ ОЦЕНКА</span>
              <strong>{selectedEntry.score?.toFixed(1) ?? '—'}</strong>
            </div>
            <div className="criteria-breakdown">
              <div><span><Icon name="sparkles" size={15} />Атмосфера</span><b>{selectedEntry.atmosphereScore?.toFixed(1) ?? '—'}</b></div>
              <div><span><Icon name="book" size={15} />Сюжет</span><b>{selectedEntry.storyScore?.toFixed(1) ?? '—'}</b></div>
              <div><span><Icon name="cpu" size={15} />Технологичность</span><b>{selectedEntry.technologyScore?.toFixed(1) ?? '—'}</b></div>
              <div><span><Icon name="gamepad" size={15} />Геймплей</span><b>{selectedEntry.gameplayScore?.toFixed(1) ?? '—'}</b></div>
            </div>
          </section>
        )}

        {isPlaythrough(selectedEntry) && (
          <section className="info-card">
            <span className="eyebrow detail-section-eyebrow">МОЁ ПРОХОЖДЕНИЕ</span>
            <div className="info-list">
              <div><span><Icon name="gamepad" size={17} />Платформа</span><strong>{selectedEntry.platform ?? 'Не указана'}</strong></div>
              <div><span><Icon name="calendar" size={17} />Дата прохождения</span><strong>{selectedEntry.completedAt ? formatDate(selectedEntry.completedAt) : '—'}</strong></div>
            </div>
            {selectedEntry.review && (
              <div className="review-box">
                <span>Мой отзыв</span>
                <p>{selectedEntry.review}</p>
              </div>
            )}
          </section>
        )}

        <section className="info-card">
          <span className="eyebrow detail-section-eyebrow">ОБ ИГРЕ</span>
          <div className="info-list">
            <div><span><Icon name="clock" size={17} />Продолжительность</span><strong>{formatPlaytime(gameDetails, loadingDetails)}</strong></div>
            <div><span><Icon name="calendar" size={17} />Дата выхода</span><strong>{formatDate(selectedGame.releaseDate) || selectedGame.year || '—'}</strong></div>
            <div><span><Icon name="gamepad" size={17} />Платформы</span><strong>{selectedGame.platforms.join(', ') || '—'}</strong></div>
            <div><span><Icon name="cpu" size={17} />Разработчик</span><strong>{selectedGame.developer || '—'}</strong></div>
          </div>
        </section>

        {gameCollections.length > 0 && (
          <section className="detail-collections" aria-labelledby="detail-collections-title">
            <div className="detail-collections__heading">
              <h2 id="detail-collections-title">Коллекции</h2>
              <span>{gameCollections.length}</span>
            </div>
            <div className="detail-collections__track">
              {gameCollections.map((collection) => {
                const collectionGames = entries
                  .filter((entry) => entry.collectionIds.includes(collection.id))
                  .flatMap((entry) => {
                    const game = catalogGames.find((item) => item.id === entry.gameId)
                    return game ? [game] : []
                  })

                return (
                  <button
                    type="button"
                    className="collection-card detail-collection-card"
                    key={collection.id}
                    onClick={() => navigateTo({
                      tab: 'collections',
                      gameId: null,
                      collectionId: collection.id,
                      formGameId: null,
                    })}
                    aria-label={`Открыть коллекцию «${collection.title}»`}
                  >
                    <div className={`collection-card__mosaic detail-collection-card__mosaic detail-collection-card__mosaic--${Math.min(collectionGames.length, 4)}`}>
                      {collectionGames.slice(0, 4).map((game) => (
                        <Cover game={game} compact key={game.id} />
                      ))}
                    </div>
                    <div className="collection-card__footer">
                      <div className="detail-collection-card__label">
                        <strong>{collection.title}</strong>
                        <span>{collectionGames.length} {collectionGames.length === 1 ? 'игра' : 'игр'}</span>
                      </div>
                      <span className="collection-card__mark">{collection.mark}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>
        )}
      </div>
    )
  }

  const renderLibrary = () => (
    <LayoutGroup id="library-motion">
      <div
        className={
          libraryControlsCollapsed
            ? 'library-sticky-stack library-sticky-stack--collapsed'
            : 'library-sticky-stack'
        }
      >
      <header className="topbar library-topbar">
        <motion.button
          layout
          className="library-title"
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

      <div className="library-control-dock">
        <motion.div
          className="library-control-clip"
          style={{
            // Render the real content before its first positive measurement;
            // otherwise the zero-initialised MotionValue hides it at startup.
            height: libraryControlsMeasured ? libraryControlClipHeight : 'auto',
            opacity: shouldReduceMotion || !libraryControlsMeasured ? 1 : libraryControlClipOpacity,
          }}
        >
          <div ref={measureLibraryControls} className="library-control-content">

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
            <strong>{personalLibraryEntries.length}</strong>
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
          ['dropped', 'Дропнуто'],
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
            <span className="library-status-card__label">{label}</span>
            <span className="library-status-card__count">{counts[status]}</span>
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
          <motion.div
            className="library-filter-panel-clip"
            initial={shouldReduceMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={shouldReduceMotion ? undefined : { height: 0, opacity: 0 }}
            transition={
              shouldReduceMotion
                ? { duration: 0 }
                : {
                    height: { duration: .24, ease: [0.22, 1, 0.36, 1] },
                    opacity: { duration: .16 },
                  }
            }
          >
            <motion.section
              className="filter-panel library-filter-panel"
              initial={shouldReduceMotion ? false : { y: -6 }}
              animate={{ y: 0 }}
              exit={shouldReduceMotion ? undefined : { y: -4 }}
              transition={{ duration: .18, ease: [0.22, 1, 0.36, 1] }}
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
          </motion.div>
        )}
      </AnimatePresence>

          </div>
        </motion.div>

        <motion.button
          className="library-dock-toggle"
          aria-label={
            libraryControlsCollapsed
              ? 'Развернуть управление библиотекой'
              : 'Свернуть управление библиотекой'
          }
          onClick={() => {
            const currentProgress = libraryCollapseProgress.get()
            const generation = ++libraryToggleGenerationRef.current
            libraryToggleAnimationRef.current?.stop()
            libraryScrollSyncPausedRef.current = true

            const expanding = currentProgress >= .5
            if (expanding) {
              libraryForceCollapsedRef.current = false
              setLibraryControlsCollapsed(false)
            }

            const controls = animate(libraryCollapseProgress, expanding ? 0 : 1, {
              type: 'spring',
              stiffness: 210,
              damping: 30,
              mass: .9,
            })
            libraryToggleAnimationRef.current = controls

            void controls.then(() => {
              if (generation !== libraryToggleGenerationRef.current) return
              libraryToggleAnimationRef.current = null
              // Wait until the changing dock height has settled before
              // resuming scroll-driven updates.
              window.requestAnimationFrame(() => {
                window.requestAnimationFrame(() => {
                  if (generation !== libraryToggleGenerationRef.current) return

                  const currentY = Math.max(0, window.scrollY)
                  libraryScrollAnchorRef.current = Math.max(4, currentY)
                  libraryEntryAnchorActiveRef.current = expanding && currentY > 4
                  libraryLastScrollYRef.current = currentY
                  libraryForcedRevealStartRef.current = null
                  libraryTopLatchRef.current = expanding && currentY <= 4
                  libraryForceCollapsedRef.current = !expanding
                  libraryScrollSyncPausedRef.current = false
                })
              })
            })
          }}
          whileTap={shouldReduceMotion ? undefined : { scale: .96 }}
        >
          <motion.span
            className="library-dock-chevron"
            initial={false}
            animate={
              libraryControlsCollapsed
                ? { rotate: 45, y: [-2, 2, -2], opacity: 1 }
                : { rotate: -135, y: [2, -2, 2], opacity: 1 }
            }
            transition={{
              rotate: { type: 'spring', stiffness: 320, damping: 28, mass: .65 },
              opacity: { duration: .12 },
              y: shouldReduceMotion
                ? { duration: 0 }
                : { duration: 1.45, repeat: Infinity, ease: 'easeInOut' },
            }}
            aria-hidden="true"
          />
        </motion.button>
      </div>
      </div>

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
                    onOpen={() => openGame(game.id)}
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
    const entryForGame = addGame ? entryMap.get(addGame.id) : undefined
    const editingEntry = isPlaythrough(entryForGame) ? entryForGame : undefined

    if (addGame) {
      return (
        <>
          <header className="subpage-header">
            <button className="icon-button" onClick={() => goBackOr({ tab: 'add', gameId: null, collectionId: null, formGameId: null })}><Icon name="back" size={20} /></button>
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
              {(['completed', 'playing', 'dropped'] as LibraryStatus[]).map((status) => (
                <button
                  key={status}
                  className={addStatus === status ? 'choice-button choice-button--active' : 'choice-button'}
                  onClick={() => setAddStatus(status)}
                >
                  {statusMeta[status].label}
                </button>
              ))}
            </div>

            <label className="form-field">
              <span>Платформа</span>
              <select value={addPlatform} onChange={(event) => setAddPlatform(event.target.value)}>
                {addGame.platforms.map((platform) => <option key={platform}>{platform}</option>)}
              </select>
            </label>

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
        <header className="topbar game-database-heading">
          <div className="game-database-heading__row">
            <h1>База игр</h1>
            <p className="game-database-powered">powered by <strong>IGDB</strong></p>
          </div>
        </header>

        {addQuery.trim().length < 3 && (
          <p className="game-database-input-hint">Введи хотя бы 3 символа для поиска.</p>
        )}
        <div className="search-wrap game-database-search">
          <Icon name="search" size={20} />
          <input
            value={addQuery}
            onChange={(event) => setAddQuery(event.target.value)}
            placeholder="Название игры..."
            aria-label="Поиск по базе игр"
          />
        </div>

        <section className="search-results">
          {addResults.map((game, index) => (
            <button
              type="button"
              className="search-result search-result--open"
              key={game.id}
              onClick={() => openGame(game.id)}
              aria-label={`Открыть игру «${game.title}»`}
            >
              <div className="search-result__cover">
                <Cover game={game} compact thumbnail priority={index < 6} />
              </div>
              <div className="search-result__copy">
                <strong>{game.title}</strong>
                <span>{game.year || 'Год не указан'} · {game.genres.slice(0, 2).join(' · ') || 'Жанр не указан'}</span>
                <small>{game.platforms.join(' · ')}</small>
              </div>
              <Icon name="arrow" size={16} />
            </button>
          ))}
        </section>

        {addSearchHasMore && !addSearchError && <div ref={addSearchSentinelRef} className="game-database-sentinel" aria-hidden="true" />}

        {addSearchLoading && (
          <div className="game-database-loading" role="status">
            <span className="game-database-loading__spinner" aria-hidden="true" />
            {addSearchSource === 'igdb' ? 'Подгружаем игры из IGDB…' : 'Ищем в базе игр…'}
          </div>
        )}

        {addSearchError && (
          <div className="game-database-error" role="alert">
            <span>{addSearchError}</span>
            <button type="button" onClick={retrySearch}>Повторить</button>
          </div>
        )}

        {addQuery.trim().length >= 3 && !addSearchLoading && !addSearchError && !addSearchHasMore && addSearchSource === 'igdb' && addResults.length === 0 && (
          <p className="game-database-empty">По этому запросу игр не нашлось. Попробуй другое название.</p>
        )}

        <AnimatePresence initial={false}>
          {addQuery.trim().length >= 3 && !addSearchLoading && !addSearchError && !addSearchHasMore && addSearchSource === 'local' && (
            <motion.button
              key="igdb-deep-search"
              type="button"
              className="game-database-deep-search"
              onClick={searchIgdb}
              initial={shouldReduceMotion ? false : { opacity: 0, y: 12, scale: .97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={shouldReduceMotion ? undefined : { opacity: 0, y: -6, scale: .98 }}
              transition={{ type: 'spring', stiffness: 330, damping: 27 }}
              whileTap={shouldReduceMotion ? undefined : { scale: .975 }}
            >
              <span className="game-database-deep-search__text">
                <strong>Не нашёл нужную игру?</strong>
                <small>Попробуй более глубокий поиск по всей базе IGDB.</small>
              </span>
              <span className="game-database-deep-search__action">
                Поиск в IGDB <Icon name="arrow" size={15} />
              </span>
            </motion.button>
          )}
        </AnimatePresence>
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
            <button className="icon-button" onClick={() => goBackOr({ tab: 'collections', gameId: null, collectionId: null, formGameId: null })}><Icon name="back" size={20} /></button>
            <div>
              <h1>{collection.title}</h1>
            </div>
          </header>
          <p className="page-lead">{collection.description}</p>
          {collection.isSystem && (
            <p className="collection-system-label"><Icon name="lock" size={13} /> Системная коллекция — всегда доступна</p>
          )}
          <div className="game-grid">
            {collectionEntries.map((entry) => {
              const game = catalogGames.find((item) => item.id === entry.gameId)!
              return <GameCard key={game.id} game={game} entry={entry} collections={collections} onOpen={() => openGame(game.id)} />
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
              <button className="collection-card" key={collection.id} title={collection.isSystem ? 'Системная коллекция — нельзя удалить' : undefined} onClick={() => navigateTo({ tab: 'collections', gameId: null, collectionId: collection.id, formGameId: null })}>
                <div className="collection-card__mosaic">
                  {items.slice(0, 4).map((game) => <Cover game={game} compact key={game.id} />)}
                  {items.length === 0 && <div className="collection-card__empty">{collection.mark}</div>}
                </div>
                <div className="collection-card__footer">
                  <div>
                    <strong>{collection.title}</strong>
                    <span>{items.length} {items.length === 1 ? 'игра' : 'игр'}{collection.isSystem ? ' · системная' : ''}</span>
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
                <button key={game.id} onClick={() => openGame(game.id)}>
                  <span className="activity-cover"><Cover game={game} compact /></span>
                  <span><strong>{game.title}</strong><small>{formatDate(entry.completedAt)}</small></span>
                  <b>{entry.score?.toFixed(1)}</b>
                </button>
              )
            })}
          </div>
        </section>

        <PushSettings user={authUser?.nickname ?? ''} />

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
              try { await disconnectPushForLogout() } catch { /* Log out regardless of push API availability. */ }
              await fetch('/api/auth/logout', { method: 'POST' })
              setAuthUser(null)
              setEntries([])
              setCollections([])
              navigateTo(
                { tab: 'library', gameId: null, collectionId: null, formGameId: null },
                { replace: true },
              )
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
    { id: 'add', label: 'База игр', icon: 'library' },
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
      <main
        className={
          activeTab === 'library' && selectedGameId == null
            ? 'page page--library'
            : 'page'
        }
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={keyForAppView(currentViewRef.current)}
            ref={restoreScreenPosition}
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

      <PushOnboarding user={authUser.nickname} />

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