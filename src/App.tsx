import { useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { games, genres, type Game } from './data'

type IconName = 'home' | 'search' | 'bookmark' | 'user' | 'heart' | 'star' | 'arrow' | 'filter'

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
    home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9"/><path d="M9 20v-6h6v6"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    bookmark: <path d="M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-4-6 4V4.5Z"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.2 3.5-6.3 8-6.3s7.2 2.1 8 6.3"/></>,
    heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>,
    star: <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>,
    arrow: <><path d="M5 12h14"/><path d="m14 7 5 5-5 5"/></>,
    filter: <><path d="M4 6h16"/><path d="M7 12h10"/><path d="M10 18h4"/></>,
  }

  return <svg {...common}>{paths[name]}</svg>
}

function Cover({ game, large = false }: { game: Game; large?: boolean }) {
  const style = {
    '--accent': game.accent,
    '--accent-2': game.accent2,
  } as CSSProperties

  return (
    <div className={large ? 'cover cover--hero' : 'cover'} style={style}>
      <div className="cover__orb cover__orb--one" />
      <div className="cover__orb cover__orb--two" />
      <span className="cover__noise" />
      <span className="cover__glyph">{game.glyph}</span>
    </div>
  )
}

function App() {
  const [query, setQuery] = useState('')
  const [activeGenre, setActiveGenre] = useState('Все')
  const [saved, setSaved] = useState<Set<number>>(new Set([4]))
  const [activeTab, setActiveTab] = useState('Главная')

  const featured = games.find((game) => game.featured) ?? games[0]

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()

    return games.filter((game) => {
      const genreMatch = activeGenre === 'Все' || game.genres.includes(activeGenre)
      const queryMatch =
        !normalized ||
        game.title.toLowerCase().includes(normalized) ||
        game.subtitle.toLowerCase().includes(normalized) ||
        game.genres.some((genre) => genre.toLowerCase().includes(normalized))

      return genreMatch && queryMatch
    })
  }, [query, activeGenre])

  const toggleSaved = (id: number) => {
    setSaved((current) => {
      const next = new Set(current)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const nav = [
    { label: 'Главная', icon: 'home' as IconName },
    { label: 'Поиск', icon: 'search' as IconName },
    { label: 'Сохранено', icon: 'bookmark' as IconName },
    { label: 'Профиль', icon: 'user' as IconName },
  ]

  return (
    <div className="app-shell">
      <main className="page">
        <header className="topbar">
          <div>
            <span className="eyebrow">ПРОТОТИП</span>
            <h1>Найди следующую игру</h1>
          </div>
          <button className="avatar" aria-label="Профиль">S</button>
        </header>

        <div className="search-wrap">
          <Icon name="search" size={20} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Игра, жанр, настроение..."
            aria-label="Поиск игр"
          />
          <button className="search-action" aria-label="Фильтры">
            <Icon name="filter" size={18} />
          </button>
        </div>

        {activeTab === 'Главная' && !query && activeGenre === 'Все' && (
          <section className="hero-card">
            <Cover game={featured} large />
            <div className="hero-card__scrim" />
            <div className="hero-card__content">
              <div className="hero-card__badges">
                <span className="pill pill--bright">{featured.match}% подходит</span>
                <span className="pill">{featured.year}</span>
              </div>
              <h2>{featured.title}</h2>
              <p>{featured.subtitle}</p>
              <div className="hero-card__footer">
                <span>{featured.genres.join(' · ')}</span>
                <button>
                  Подробнее <Icon name="arrow" size={17} />
                </button>
              </div>
            </div>
          </section>
        )}

        <section className="genre-strip" aria-label="Жанры">
          {genres.map((genre) => (
            <button
              key={genre}
              className={activeGenre === genre ? 'genre-chip genre-chip--active' : 'genre-chip'}
              onClick={() => setActiveGenre(genre)}
            >
              {genre}
            </button>
          ))}
        </section>

        <section className="catalog">
          <div className="section-heading">
            <div>
              <span className="eyebrow">{query ? 'РЕЗУЛЬТАТЫ' : 'ДЛЯ ТЕБЯ'}</span>
              <h2>{query ? 'Нашли: ' + filtered.length : 'Стоит попробовать'}</h2>
            </div>
            <button className="text-button">Все</button>
          </div>

          {filtered.length > 0 ? (
            <div className="game-grid">
              {filtered.map((game) => (
                <article className="game-card" key={game.id}>
                  <div className="game-card__cover-wrap">
                    <Cover game={game} />
                    <button
                      className={saved.has(game.id) ? 'save-button save-button--active' : 'save-button'}
                      onClick={() => toggleSaved(game.id)}
                      aria-label={saved.has(game.id) ? 'Убрать из сохранённых' : 'Сохранить'}
                    >
                      <Icon name="heart" size={18} />
                    </button>
                    <span className="match-badge">{game.match}%</span>
                  </div>
                  <div className="game-card__body">
                    <div className="game-card__title-row">
                      <h3>{game.title}</h3>
                      <span className="rating"><Icon name="star" size={14} /> {game.rating}</span>
                    </div>
                    <p>{game.subtitle}</p>
                    <div className="game-card__meta">
                      <span>{game.genres[0]}</span>
                      <span>•</span>
                      <span>{game.year}</span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <span>Ничего не нашли</span>
              <p>Попробуй другой запрос или сбрось фильтр жанра.</p>
              <button onClick={() => { setQuery(''); setActiveGenre('Все') }}>Сбросить фильтры</button>
            </div>
          )}
        </section>

        <section className="prototype-note">
          <span className="prototype-note__dot" />
          <div>
            <strong>Сейчас используются тестовые данные</strong>
            <p>Позже заменим их на данные из IGDB через наш Python API.</p>
          </div>
        </section>
      </main>

      <nav className="bottom-nav" aria-label="Основная навигация">
        {nav.map((item) => (
          <button
            key={item.label}
            onClick={() => setActiveTab(item.label)}
            className={activeTab === item.label ? 'bottom-nav__item bottom-nav__item--active' : 'bottom-nav__item'}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}

export default App
