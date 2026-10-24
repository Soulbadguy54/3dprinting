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
  const y = stage.y + (direction === 'up' ? stage.height * .48 : Math.min(stage.height * .27, 180))
  await movePointer(page, x, y, x + (direction === 'left' ? -160 : direction === 'right' ? 160 : 0),
    y + (direction === 'up' ? -190 : 0))
}

async function dragHandle(page: Page, delta: number, simulateTouch = false) {
  if (simulateTouch) {
    // WebKit's Mouse API does not simulate a continuous iPhone touch drag.
    // Exercise our cross-browser fallback with a continuous DOM mouse stream.
    // Native touch has a parallel onTouchStart/touchmove/touchend path in the app.
    await page.evaluate(dy => {
      const handle = document.querySelector<HTMLButtonElement>('.discover-sheet__handle')
      if (!handle) throw new Error('Sheet handle absent')
      const box = handle.getBoundingClientRect()
      const x = box.left + box.width / 2
      const y = box.top + box.height / 2
      handle.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, buttons: 1,
      }))
      for (let i = 1; i <= 14; i++) {
        window.dispatchEvent(new MouseEvent('mousemove', {
          bubbles: true, cancelable: true, clientX: x, clientY: y + dy * i / 14, buttons: 1,
        }))
      }
      window.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true, cancelable: true, clientX: x, clientY: y + dy, button: 0,
      }))
    }, delta)
    return
  }
  const handle = await page.getByRole('button', { name: /подробности/i }).boundingBox()
  if (!handle) throw new Error('Sheet handle absent')
  const x = handle.x + handle.width / 2
  const y = handle.y + handle.height / 2
  await movePointer(page, x, y, x, y + delta)
}

test('integrated discovery: fitted poster, calm glass, tutorial, directions and undo', async ({ page }) => {
  const nickname = 'disc_' + Date.now().toString(36).slice(-8)
  const onIPhone = test.info().project.name.includes('WebKit')
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
  await expect(page.locator('.bottom-nav')).toBeVisible()
  await expect(page.locator('.page')).toHaveClass(/page--discovery/)
  await expect(page.locator('.bottom-nav')).toBeVisible()
  await expect(page.getByText('Discovery One')).toBeVisible()
  await expect(page.getByText('Новые игры для тебя')).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'Обучение рекомендациям' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Закрыть обучение' })).toHaveCount(1)
  await expect(page.getByText('Хочу поиграть').first()).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть обучение' }).click()
  await expect(page.getByRole('button', { name: 'Закрыть обучение' })).toHaveCount(0)
  await expect(page.getByText('Discovery One')).toBeVisible()
  await expect(page.locator('.discover-cover__poster .cover')).toBeVisible()
  await expect(page.locator('.discover-cover__poster .cover__image')).toHaveCSS('object-fit', 'contain')
  const stageRect = await page.locator('.discover-stage').boundingBox()
  const coverRect = await page.locator('.discover-cover__poster').boundingBox()
  const sheetRect = await page.locator('.discover-sheet').boundingBox()
  const topbarRect = await page.locator('.discover-topbar').boundingBox()
  const navbarRect = await page.locator('.bottom-nav').boundingBox()
  const viewport = page.viewportSize()
  if (!stageRect || !coverRect || !sheetRect || !topbarRect || !navbarRect || !viewport)
    throw new Error('Discovery geometry missing')
  // Exactly one poster between the real top and bottom navigation: edge-to-edge,
  // with no inherited .page left/right padding, margin or bottom gap.
  expect(Math.abs(stageRect.x)).toBeLessThan(2)
  expect(Math.abs(stageRect.width - viewport.width)).toBeLessThan(2)
  expect(Math.abs(stageRect.y - (topbarRect.y + topbarRect.height))).toBeLessThan(2)
  expect(Math.abs((stageRect.y + stageRect.height) - navbarRect.y)).toBeLessThan(2)
  expect(Math.abs(coverRect.width - stageRect.width)).toBeLessThan(2)
  expect(Math.abs(coverRect.height - stageRect.height)).toBeLessThan(2)
  expect(Math.abs(coverRect.x - stageRect.x)).toBeLessThan(2)
  expect(sheetRect.height / stageRect.height).toBeGreaterThan(.78)
  expect(sheetRect.height / stageRect.height).toBeLessThan(.82)
  // Collapsed glass occupies only a short portion of the visible poster.
  const visibleGlass = stageRect.y + stageRect.height - sheetRect.y
  expect(visibleGlass).toBeLessThan(170)
  // Hints share one synchronized 7.5-second fade cycle, not a blinking garland.
  for (const hint of await page.locator('.discover-hint').all()) {
    await expect(hint).toHaveCSS('animation-duration', '7.5s')
    await expect(hint).toHaveCSS('animation-delay', '0s')
  }
  await expect(page.locator('.discover-sheet__ratings')).toContainText('IGDB')
  await expect(page.locator('.discover-sheet__ratings')).toContainText('Rate APP')
  await expect(page.locator('.discover-actions')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Развернуть подробности' })).toHaveAttribute('aria-expanded', 'false')

  // Short pull returns to the initial sheet position.
  const posterBeforePull = await page.locator('.discover-cover__poster').boundingBox()
  await dragHandle(page, -30, onIPhone)
  await expect(page.getByRole('button', { name: 'Развернуть подробности' })).toHaveAttribute('aria-expanded', 'false')
  const posterAfterPull = await page.locator('.discover-cover__poster').boundingBox()
  expect(posterAfterPull?.y).toBeCloseTo(posterBeforePull?.y ?? 0, 0)
  // Long pull expands and reveals actual details.
  await dragHandle(page, -245, onIPhone)
  await expect(page.getByRole('button', { name: 'Свернуть подробности' })).toHaveAttribute('aria-expanded', 'true')
  // The glass, not the cover, moves upward and occludes 80% of the art.
  await expect.poll(async () => {
    const glass = await page.locator('.discover-sheet').boundingBox()
    const stage = await page.locator('.discover-stage').boundingBox()
    if (!glass || !stage) return -1
    return (stage.y + stage.height - glass.y) / stage.height
  }, { timeout: 3500 }).toBeGreaterThan(.77)
  const posterExpanded = await page.locator('.discover-cover__poster').boundingBox()
  expect(posterExpanded?.y).toBeCloseTo(posterBeforePull?.y ?? 0, 0)
  await expect(page.getByText('A great story about stars.')).toBeVisible()
  await expect(page.getByRole('link', { name: /Steam/ })).toBeVisible()
  // While details are expanded, swiping the poster must not submit a like/dislike.
  await dragCover(page, 'right')
  expect(actions).toHaveLength(0)
  // Reverse drag collapses the sheet.
  await dragHandle(page, 270, onIPhone)
  await expect(page.getByRole('button', { name: 'Развернуть подробности' })).toHaveAttribute('aria-expanded', 'false')
  // The sheet finishes its deliberate, non-jelly snap before a new gesture.
  await page.waitForTimeout(420)

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
  await expect(page.getByRole('button', { name: 'Закрыть обучение' })).toHaveCount(0)
  await expect(page.getByText('Discovery Two')).toBeVisible()
  await dragCover(page, 'up')
  await expect(page.getByText('Пока всё просмотрено')).toBeVisible()
  expect(actions).toEqual(['like', 'dislike', 'wishlist'])
  await page.getByRole('button', { name: 'Вернуться в базу игр' }).click()
  await expect(page.getByRole('heading', { name: 'База игр' })).toBeVisible()
  await expect(page.locator('.bottom-nav')).toBeVisible()
})
