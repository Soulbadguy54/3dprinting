import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

// Playwright route mocks must not be intercepted by the installed PWA worker.
test.use({ serviceWorkers: 'block' })

async function movePointer(page: Page, fromX: number, fromY: number, toX: number, toY: number) {
  await page.mouse.move(fromX, fromY)
  await page.mouse.down()
  await page.mouse.move(toX, toY, { steps: 12 })
  await page.mouse.up()
}

async function dragCover(page: Page, direction: 'left' | 'right' | 'up') {
  const stage = await page.locator('.discover-stage').boundingBox()
  if (!stage) throw new Error('Discovery stage absent')
  const x = stage.x + stage.width * .5
  const y = stage.y + Math.min(stage.height * .27, 180)
  await movePointer(page, x, y, x + (direction === 'left' ? -160 : direction === 'right' ? 160 : 0),
    y + (direction === 'up' ? -145 : 0))
}

async function dragHandle(page: Page, delta: number) {
  const handle = await page.getByRole('button', { name: /подробности/i }).boundingBox()
  if (!handle) throw new Error('Sheet handle absent')
  const x = handle.x + handle.width / 2
  const y = handle.y + handle.height / 2
  await movePointer(page, x, y, x, y + delta)
}

test('full screen discovery: one tutorial, draggable sheet, swipe direction and undo', async ({ page }) => {
  const nickname = 'disc_' + Date.now().toString(36).slice(-8)
  const game = (id: number, title: string) => ({
    id, title, genres: ['Action', 'RPG'], year: 2025,
    releaseDate: '2025-06-12', developer: 'Example Studio',
    platforms: ['PC', 'PlayStation 5'], igdbRating: 89,
    communityRating: 8.6, communityRatings: 3,
    accent: '#9976ec', accent2: '#32275c', glyph: 'DS',
    coverUrl: 'https://images.igdb.com/igdb/image/upload/t_cover_big_2x/co123.jpg',
  })
  const actions: string[] = []
  await page.route('**/api/discover/feed', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ items: [game(900000001, 'Discovery One'), game(900000002, 'Discovery Two')], remaining: 2 }),
  }))
  await page.route('**/api/discover/feedback', async route => {
    const post = route.request().postDataJSON() as { action: string }
    actions.push(post.action)
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
  })
  await page.route('**/api/discover/feedback/*', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"ok":true}',
  }))
  await page.route('**/api/games/900000001/details', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      summary: 'A great story about stars.',
      storeLinks: [{ provider: 'steam', label: 'Steam', url: 'https://store.steampowered.com/app/1234' }],
      trailerUrl: null,
    }),
  }))
  await page.goto('/')
  await page.getByRole('button', { name: 'Регистрация' }).click()
  await page.locator('input[type=email]').fill(nickname + '@example.com')
  await page.locator('input[autocomplete=username]').fill(nickname)
  await page.locator('input[autocomplete=new-password]').first().fill('29843571')
  await page.locator('input[autocomplete=new-password]').last().fill('29843571')
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()
  await expect(page.locator('.bottom-nav')).toBeVisible()
  const installClose = page.getByRole('button', { name: 'Закрыть предложение установки' })
  if (await installClose.isVisible()) await installClose.click()
  await page.locator('.bottom-nav__item').filter({ hasText: 'База игр' }).click()
  await page.getByRole('button', { name: 'Открыть рекомендации игр' }).click()
  await expect(page.locator('.discover-screen')).toBeVisible()
  await expect(page.locator('.bottom-nav')).toHaveCount(0)
  await expect(page.getByText('Новые игры для тебя')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Закрыть обучение' })).toHaveCount(1)
  await expect(page.getByText('Хочу поиграть').first()).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть обучение' }).click()
  await expect(page.getByRole('button', { name: 'Закрыть обучение' })).toHaveCount(0)
  await expect(page.getByText('Discovery One')).toBeVisible()
  await expect(page.locator('.discover-cover .cover')).toBeVisible()
  await expect(page.locator('.discover-sheet__ratings')).toContainText('IGDB')
  await expect(page.locator('.discover-sheet__ratings')).toContainText('Rate APP')
  await expect(page.locator('.discover-actions')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Развернуть подробности' })).toHaveAttribute('aria-expanded', 'false')

  // Short pull returns to the initial sheet position.
  await dragHandle(page, -30)
  await expect(page.getByRole('button', { name: 'Развернуть подробности' })).toHaveAttribute('aria-expanded', 'false')
  // Long pull expands and reveals actual details.
  await dragHandle(page, -245)
  await expect(page.getByRole('button', { name: 'Свернуть подробности' })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('A great story about stars.')).toBeVisible()
  await expect(page.getByRole('link', { name: /Steam/ })).toBeVisible()
  // While details are expanded, swiping the poster must not submit a like/dislike.
  await dragCover(page, 'right')
  expect(actions).toHaveLength(0)
  // Reverse drag collapses the sheet.
  await dragHandle(page, 270)
  await expect(page.getByRole('button', { name: 'Развернуть подробности' })).toHaveAttribute('aria-expanded', 'false')
  // The physical panel needs to finish spring-snapping before another gesture.
  await page.waitForTimeout(700)

  // Right means LIKE, left means DISLIKE; not the reversed direction from v1.
  await dragCover(page, 'right')
  await expect(page.getByText('Discovery Two')).toBeVisible()
  expect(actions).toEqual(['like'])
  await page.getByRole('button', { name: 'Шаг назад' }).click()
  await expect(page.getByText('Discovery One')).toBeVisible()
  await dragCover(page, 'left')
  await expect(page.getByText('Discovery Two')).toBeVisible()
  expect(actions).toEqual(['like', 'dislike'])
  // The info icon reopens the same ONE-frame onboarding.
  await page.getByRole('button', { name: 'Показать обучение' }).click()
  await expect(page.getByText('Новые игры для тебя')).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть обучение' }).click()
  await expect(page.getByText('Discovery Two')).toBeVisible()
  await dragCover(page, 'up')
  await expect(page.getByText('Пока всё просмотрено')).toBeVisible()
  expect(actions).toEqual(['like', 'dislike', 'wishlist'])
  await page.getByRole('button', { name: 'Вернуться в базу игр' }).click()
  await expect(page.getByRole('heading', { name: 'База игр' })).toBeVisible()
  await expect(page.locator('.bottom-nav')).toBeVisible()
})
