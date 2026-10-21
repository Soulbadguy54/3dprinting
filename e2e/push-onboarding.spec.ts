import { test, expect } from '@playwright/test'

test('auth screen remains usable if push configuration fails', async ({ page }) => {
  await page.route('**/api/push/config', route => route.abort())
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Войти' })).toBeVisible()
})

test('first opt-in recovers when device push provider does not respond', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'Web Push on iOS requires an installed Home Screen PWA.')
  await page.context().grantPermissions(['notifications'])
  await page.addInitScript(() => {
    Object.defineProperty(PushManager.prototype, 'getSubscription', {
      configurable: true, value: () => Promise.resolve(null),
    })
    Object.defineProperty(PushManager.prototype, 'subscribe', {
      configurable: true, value: () => new Promise(() => {}),
    })
  })
  await page.route('**/api/push/config', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ enabled: true, publicKey: 'B'.repeat(87), devices: 0 }),
  }))

  const nickname = 'push_' + Date.now().toString(36).slice(-8)
  await page.goto('/')
  await page.getByRole('button', { name: 'Регистрация' }).click()
  await page.locator('input[type=email]').fill(nickname + '@example.com')
  await page.locator('input[autocomplete=username]').fill(nickname)
  await page.locator('input[autocomplete=new-password]').first().fill('29843571')
  await page.locator('input[autocomplete=new-password]').last().fill('29843571')
  await page.getByRole('button', { name: 'Создать аккаунт' }).click()

  const invite = page.getByRole('dialog', { name: 'Не пропусти выход игры' })
  await expect(invite).toBeVisible()
  await page.clock.install()
  await invite.getByRole('button', { name: 'Включить уведомления' }).click()
  await expect(invite.getByText('Подключаем Push-службу устройства…')).toBeVisible()
  await page.clock.fastForward(20_100)
  await expect(invite.getByText(/Push-служба устройства не ответила за 20 секунд/)).toBeVisible()
  await expect(invite.getByRole('button', { name: 'Включить уведомления' })).toBeEnabled()
})
