import { test, expect } from '@playwright/test'

test('desktop Chrome shows the mobile-only notice instead of an empty background', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Пока только на мобильных' })).toBeVisible()
  await expect(page.locator('.rateapp-desktop-gate__overlay')).toBeVisible()
})
