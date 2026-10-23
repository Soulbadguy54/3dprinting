# Проверка тестового контура Rate APP

Адрес: https://dev.r-app.ru

Первоначальный вход — существующий аккаунт `soulbadguy` с тем же PIN, что на production. Не передавать PIN в чат. Регистрация на тестовом сайте отсутствует и на backend заблокирована.

После первого запуска проверить мобильный внешний вид, красную метку `TEST · DEV`, разделы «Мои игры», коллекции и wishlist. Данные являются копией; изменения на dev не должны появляться на https://r-app.ru.

CI/CD: PR в develop → frontend/backend/mobile tests → `VPS staging deployment` → smoke. Production обновляется только из `main` после пользовательской приёмки.

Если на dev появилась ошибка 502 до окончания первого deploy, нельзя считать staging готовым. Проверить workflow, `/api/health` и данные `rateapp_stage`.
