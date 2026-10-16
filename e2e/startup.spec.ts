import { test, expect } from '@playwright/test'

test('missing versioned JavaScript displays a working recovery control', async ({ page }) => {
  await page.route('**/assets/index-*.js', (route) =>
    route.fulfill({ status: 404, contentType: 'text/plain', body: 'Missing old chunk' }),
  )
  await page.goto('/')
  await expect(page.locator('[data-rateapp-recovery]')).toBeVisible({ timeout: 16_000 })
  await expect(page.getByRole('button', { name: 'Восстановить загрузку' })).toBeVisible()
  await page.unroute('**/assets/index-*.js')
  await page.getByRole('button', { name: 'Восстановить загрузку' }).click()
  await expect(page.getByRole('heading', { name: 'Войти' })).toBeVisible({ timeout: 20_000 })
})
