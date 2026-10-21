import { test, expect } from '@playwright/test'

test('auth screen stays usable when push configuration is unavailable', async ({ page }) => {
  await page.route('**/api/push/config', route => route.abort())
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Войти' })).toBeVisible()
})
