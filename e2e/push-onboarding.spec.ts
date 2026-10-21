import { test, expect } from '@playwright/test'

// Push subscription is intentionally exercised without a live push provider.
test('mobile app retains its signed-out state when push settings are unavailable', async ({ page }) => {
  await page.route('**/api/push/config', route => route.abort())
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Войти' })).toBeVisible()
})
