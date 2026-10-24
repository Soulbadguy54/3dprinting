import { test, expect } from '@playwright/test'

// Service workers can intercept fetch before Playwright route mocks on mobile.
test.use({ serviceWorkers: 'block' })

test('discovery onboarding, swipe, undo and animated details', async ({ page }) => {
  page.on('pageerror', error => console.log('DISCOVERY PAGEERROR', error.message))
  const nickname = 'disc_' + Date.now().toString(36).slice(-8)
  const game = (id: number, title: string) => ({
    id, title, genres: ['Action', 'RPG'], year: 2025,
    releaseDate: '2025-06-12', developer: 'Example Studio',
    platforms: ['PC', 'PlayStation 5'], igdbRating: 89,
    communityRating: 0, communityRatings: 0,
    accent: '#9976ec', accent2: '#32275c', glyph: 'DS',
    coverUrl: 'https://images.igdb.com/igdb/image/upload/t_cover_big_2x/co123.jpg',
  })
  await page.route('**/api/discover/feed', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      items: [game(900000001, 'Discovery One'), game(900000002, 'Discovery Two')],
      remaining: 2,
    }),
  }))
  await page.route('**/api/discover/feedback', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"ok":true}',
  }))
  await page.route('**/api/discover/feedback/*', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"ok":true}',
  }))
  await page.route('**/api/games/900000001/details', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ summary: 'A great story about stars.',
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
  console.log('DISCOVERY SCREEN:', (await page.locator('.discover-screen').innerText()).slice(0,700))
  await expect(page.getByText('Discovery One')).toBeVisible()
  await expect(page.getByText('Твои новые игры')).toBeVisible()
  const helper = page.getByRole('button', { name: 'Следующий шаг обучения' })
  for (let i = 0; i < 5; i++) await helper.click()
  await expect(helper).toHaveCount(0)
  await page.getByRole('button', { name: 'Свайп вниз — подробнее' }).click()
  await expect(page.getByText('A great story about stars.')).toBeVisible()
  await expect(page.getByRole('link', { name: /Steam/ })).toBeVisible()
  await page.getByRole('button', { name: /Свернуть подробности/ }).click()
  await page.getByRole('button', { name: 'Нравится, следующая игра', exact: true }).click()
  await expect(page.getByText('Discovery Two')).toBeVisible()
  await page.getByRole('button', { name: /Шаг назад/ }).click()
  await expect(page.getByText('Discovery One')).toBeVisible()
  await page.getByRole('button', { name: 'Показать обучение' }).click()
  await expect(page.getByText('Твои новые игры')).toBeVisible()
})
