import type { LibraryStatus } from './data'
import type { IconName } from './components/Icon'

export const statusMeta: Record<LibraryStatus, { label: string; short: string }> = {
  completed: { label: 'Пройдено', short: 'Пройдено' },
  playing: { label: 'Прохожу', short: 'Прохожу' },
  wishlist: { label: 'В коллекции', short: 'В коллекции' },
  untracked: { label: 'В коллекции', short: 'В коллекции' },
  dropped: { label: 'Дропнуто', short: 'Дропнуто' },
}

export const statusIcons: Record<LibraryStatus, IconName> = {
  completed: 'check',
  playing: 'play',
  wishlist: 'bookmark',
  untracked: 'layers',
  dropped: 'close',
}

export const ratedStatuses = new Set<LibraryStatus>(['completed', 'dropped'])

