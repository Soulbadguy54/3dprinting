export type Game = {
  id: number
  title: string
  subtitle: string
  genres: string[]
  platform: string
  year: number
  rating: number
  match: number
  accent: string
  accent2: string
  glyph: string
  featured?: boolean
}

export const genres = ['Все', 'RPG', 'Экшен', 'Инди', 'Стратегия', 'Гонки', 'Кооператив']

export const games: Game[] = [
  {
    id: 1,
    title: 'Neon Divide',
    subtitle: 'Город помнит каждое твоё решение',
    genres: ['RPG', 'Экшен'],
    platform: 'PC · PS5 · Xbox',
    year: 2026,
    rating: 92,
    match: 98,
    accent: '#8cf27d',
    accent2: '#2c6bff',
    glyph: 'ND',
    featured: true,
  },
  {
    id: 2,
    title: 'Ashes of Meridian',
    subtitle: 'Мрачное приключение на краю мира',
    genres: ['RPG'],
    platform: 'PC · PS5',
    year: 2025,
    rating: 88,
    match: 94,
    accent: '#ff8b63',
    accent2: '#8b3dff',
    glyph: 'AM',
  },
  {
    id: 3,
    title: 'Driftline',
    subtitle: 'Ночные трассы и живые соперники',
    genres: ['Гонки'],
    platform: 'PC · Xbox',
    year: 2026,
    rating: 84,
    match: 89,
    accent: '#54d8ff',
    accent2: '#0067ff',
    glyph: 'DL',
  },
  {
    id: 4,
    title: 'Tiny Kingdoms',
    subtitle: 'Большая стратегия в маленьком мире',
    genres: ['Стратегия', 'Инди'],
    platform: 'PC · Switch',
    year: 2024,
    rating: 91,
    match: 91,
    accent: '#ffd56b',
    accent2: '#f17f5a',
    glyph: 'TK',
  },
  {
    id: 5,
    title: 'Signal Lost',
    subtitle: 'Кооперативная экспедиция в неизвестность',
    genres: ['Кооператив', 'Экшен'],
    platform: 'PC · PS5 · Xbox',
    year: 2025,
    rating: 86,
    match: 87,
    accent: '#fb6ea9',
    accent2: '#713cff',
    glyph: 'SL',
  },
  {
    id: 6,
    title: 'Paper Skies',
    subtitle: 'Тихое путешествие над облаками',
    genres: ['Инди'],
    platform: 'PC · Switch',
    year: 2025,
    rating: 95,
    match: 96,
    accent: '#a7efff',
    accent2: '#7b8dff',
    glyph: 'PS',
  },
]
