import { test, expect } from '@playwright/test'

test('temporary 503 never masquerades as a logout', async ({ page }) => {
  await page.route('**/api/bootstrap', route =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Unavailable"}' }),
  )
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Сервер временно недоступен' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Повторить попытку' })).toBeVisible()

  await page.unroute('**/api/bootstrap')
  await page.getByRole('button', { name: 'Повторить попытку' }).click()
  await expect(page.getByRole('heading', { name: 'Войти' })).toBeVisible()
})

test('mobile registration, collections and account backup', async ({ page }) => {
  const nickname = 'e2e_' + Date.now().toString(36).slice(-8)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Войти' })).toBeVisible()
  await page.getByRole('button', { name: 'Регистрация' }).click()
  await page.locator('input[type=email]').fill(nickname + '@example.com')
  await page.locator('input[autocomplete=username]').fill(nickname)
  await page.locator('input[autocomplete=new-password]').first().fill('29843571')
  await page.locator('input[autocomplete=new-password]').last().fill('29843571')
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()
  await expect(page.locator('.bottom-nav')).toBeVisible()
  // PWA install invite may appear after login. Dismiss before tapping bottom nav.
  const installClose = page.getByRole('button', { name: 'Закрыть предложение установки' })
  if (await installClose.isVisible()) await installClose.click()

  await page.locator('.bottom-nav__item').filter({ hasText: 'Коллекции' }).click()
  await expect(page.getByRole('heading', { name: 'Коллекции' })).toBeVisible()
  await page.getByRole('button', { name: 'Создать коллекцию' }).first().click()
  await expect(page.getByRole('heading', { name: 'Новая коллекция' })).toBeVisible()
  await page.locator('input[placeholder="Например, Лучшие RPG"]').fill('Playwright smoke')
  await page.locator('.collection-create-submit').click()
  await expect(page.getByText('Playwright smoke').first()).toBeVisible()

  await page.locator('.bottom-nav__item').filter({ hasText: 'Профиль' }).click()
  await expect(page.getByRole('link', { name: /Скачать данные/ })).toBeVisible()
  const backup = await page.request.get('/api/export', { failOnStatusCode: true })
  const body = await backup.json()
  expect(body.format).toBe('rateapp-export')
  expect(body.nickname).toBe(nickname)
  expect(body.collections.some((c: { title: string }) => c.title === 'Playwright smoke')).toBe(true)

  // Exercise the same long-press selection and confirmed bulk-remove flow
  // that mobile users invoke, against real API + PostgreSQL.
  const collection = body.collections.find((c: { title: string }) => c.title === 'Playwright smoke')
  const added = await page.request.put(`/api/library/1/collections/${collection.id}`)
  expect(added.status()).toBe(200)
  await page.goto(`/?tab=collections&collection=${encodeURIComponent(collection.id)}`)
  await expect(page.locator('.game-card')).toHaveCount(1)
  const card = page.locator('.game-card').first()
  await card.dispatchEvent('pointerdown', { pointerId: 17, button: 0, clientX: 20, clientY: 20 })
  await expect(card).toHaveAttribute('aria-pressed', 'true', { timeout: 4000 })
  await card.dispatchEvent('pointerup', { pointerId: 17, button: 0, clientX: 20, clientY: 20 })
  await page.getByRole('button', { name: /Убрать выбранные игры из коллекции/ }).click()
  await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Удалить' }).click()
  await expect(page.locator('.game-card')).toHaveCount(0)
  const libraryResponse = await page.request.get('/api/library')
  expect(libraryResponse.status()).toBe(200)
  expect((await libraryResponse.json()).every(
    (entry: { collectionIds: string[] }) => !entry.collectionIds.includes(collection.id)
  )).toBe(true)
})
