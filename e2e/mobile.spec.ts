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
})
