# Rate APP — история разработки

**Цель:** проверяемая межчатовая история. **По состоянию на 19.10.2026.** Каждая запись отражает слитые изменения или явно помеченную операционную оговорку; незавершённые идеи не объявляются реализованными. Ссылки: [контекст](docs/PROJECT_CONTEXT.md), [решения](docs/DECISIONS.md), [правила для агентов](AGENTS.md).

## 19 октября 2026 — единая память проекта и docs-only CI/CD

- [PR #38](https://github.com/Soulbadguy54/RateApp/pull/38) — **документационный аудит:** заменены ссылки на прежнее имя репозитория, исправлена точка отсчёта `main` и отражён подтверждённый результат Vercel для PR #37. Изменения ограничены Markdown; проверки — сверка ссылок, целевых файлов и diff. Новый production build для исправления документации не требуется.

- [PR #36](https://github.com/Soulbadguy54/RateApp/pull/36): в репозитории заведены `AGENTS.md`, `CHANGELOG.md`, `docs/PROJECT_CONTEXT.md`, `docs/DECISIONS.md`; восстановлены контекст продукта, основные инженерные решения, хронология по merged PR и аудитам. CI (сборка, backend, Android/iPhone e2e) прошёл, первый production с новой конфигурацией READY.
- В `vercel.json` добавлено правило `ignoreCommand` через `scripts/ignore-docs-build.sh`: коммиты только с Markdown-документацией не пересобирают сайт. При изменениях кода или невозможности достоверно проверить Git diff — сборку не пропускать.
- `README.md` синхронизирован с фактическим FastAPI/PostgreSQL/PWA состоянием; тесты проверяют разницу docs-only и code+docs.
- [PR #37](https://github.com/Soulbadguy54/RateApp/pull/37) / `4205f7e`: изменение только `CHANGELOG.md` подтвердило Vercel Ignored Build Step. В логах `scripts/ignore-docs-build.sh` вывел `Skip: only repository Markdown documentation changed.`, завершился с кодом 0; production deployment для этого коммита получил статус `CANCELED` (это ожидаемый skip), новая READY-сборка не создавалась. Последний READY production deployment на тот момент относился к PR #36.
- **Ограничения:** пропущенная попытка может учитываться Vercel в квоте. На момент проверки метаданные Git-интеграции Vercel продолжали использовать старое имя `3dprinting`; актуальный GitHub-репозиторий — `Soulbadguy54/RateApp`. Это не свидетельствует о сломанном деплое, но настройки интеграции стоит проверить отдельно.

## 17 октября 2026 — оценивание, возврат назад и профиль

- [PR #35](https://github.com/Soulbadguy54/RateApp/pull/35) / `33056bdc`: шаг барабанов оценок **0,5** вместо 0,1, включая touch/keyboard. Старые баллы в БД не перезаписывались.
- Исправлен дефект `База игр → поиск → карточка → + → сохранить → карточка → назад`: возвращаться к поиску без второй карточки, сохранять строку поиска и результаты.
- Отдельный `/api/games/{id}/community-rating` без кэширования + защита от устаревших деталей IGDB; общий рейтинг учитывает последние сохранённые оценки других пользователей; правильное округление до 0,1.
- В профиле `Резервное копирование` без дублирующего заголовка экспорта, версия приложения внизу. Исправлен отсутствовавший импорт исключения в обработке загрузки жанров.
- GitHub CI: сборка, backend PostgreSQL и Android/iPhone e2e прошли. Production deployment READY; /api/health 200 на момент релиза.

## 16 октября 2026 — стабилизация, Chrome/PWA, оптимизация и wishlist

- [PR #34](https://github.com/Soulbadguy54/RateApp/pull/34) / `7954f09b`: системная коллекция «Хочу пройти» получила красное **❤️**, в UI и для уже созданных коллекций (миграция отображения).
- Коммиты `936423b2`, `592037a9`: исправлен пустой экран в Chrome после устаревшего PWA bundle (восстановление JS, безопасный старт, smoke-тест).
- `700e89f5`: градиенты карточек коллекций заметно приглушены по просьбе, без ухудшения видимости текста и эмодзи.
- Серия коммитов `2ecb0de6`, `7f435439`, `6e5bc4b2`, `b5db792c`, `6bc2a7ca`, `b5258750`, `8dd7797d`: отдельные маршруты API и компоненты профиля/эмодзи/колёс, оптимизация индекса членства, разбиение CSS, документ повторного [аудита](docs/stability-audit-2026-10-16.md).
- Дополнительно: Alembic read-only baseline, а не DDL на cold start; session-failure recovery, мобильные Playwright E2E iOS/Android, JS budget, регистрация и экспорт; CI и ежедневный production smoke. Различать реализацию тестов от **не подтверждённой** внешней настройки Sentry/бэкапов/gate.

## 15 октября 2026 — перенос данных, ограничения, UI и PWA

### Целостность истории и пользовательских данных

- [PR #32](https://github.com/Soulbadguy54/RateApp/pull/32), [PR #33](https://github.com/Soulbadguy54/RateApp/pull/33): условные CHECK на обязательные поля completed/dropped (дата, платформа, 4 оценки); playing без обязательных даты и платформы; названия/цвета коллекций валидируются.
- Для двух исторических аккаунтов дозаполнены **178** записей: дата **15.10.2026 — техническая дата миграции**, платформа по приоритету PC→PS5→PS4; **8** PS4 fallback без совпадения с IGDB, отмечены в аудите. По production health тогда: `unresolvedTargetRows=0`, `constraintValidated=true`.
- [PR #26](https://github.com/Soulbadguy54/RateApp/pull/26): сохранение полных четырёх критериев, вычисляемый итог и запрет оценок в wishlist/playing.
- [PR #28](https://github.com/Soulbadguy54/RateApp/pull/28)–[PR #31](https://github.com/Soulbadguy54/RateApp/pull/31): перенос Google Sheets и Stash Beaten с проверкой дубликатов, неоднозначных IGDB релизов и раздельных оценок; удаление одноразовых импортных маршрутов, сохранение журнала и [аудита](docs/import-audit-2026-10-15.md).
- Из Google **71 оценённая игра/аккаунт**, из Stash Beaten ещё **18/аккаунт**, суммарно **89 и 89** по этим операциям. Отдельно импортированы Stash Want: **52 членства в wishlist** (только soulbadguy), Stash Collections: **3 коллекции, 44 членства**; Stash Archived — **15 пунктов для ручной сверки, не массовый импорт**.
- **Шесть** игр из Google без полного набора четырёх оценок остаются в [аудите](docs/import-audit-2026-10-15.md). Не генерировать для них оценки и не копировать данные из других игр.

### Интерфейс и приложение

- [PR #24](https://github.com/Soulbadguy54/RateApp/pull/24), [PR #25](https://github.com/Soulbadguy54/RateApp/pull/25): новый экран прохождения, четыре барабана оценок, анимации, компактные колёса, поле даты дропа. Позже шаг колёс изменён на 0,5 в PR #35.
- [PR #18](https://github.com/Soulbadguy54/RateApp/pull/18)–[PR #23](https://github.com/Soulbadguy54/RateApp/pull/23): загрузочный экран и оформление PWA, оптимизация прогресса, приглашение установки iOS/Android, `/install`, desktop gate и валидация длины nickname/коллекций на UI и API.
- [PR #16](https://github.com/Soulbadguy54/RateApp/pull/16), [PR #17](https://github.com/Soulbadguy54/RateApp/pull/17): история вкладок/возврата, сохранение положения скролла, анимированные карточки, работа bottom nav.

## 13–14 октября 2026 — каталог IGDB, коллекции, поиск и Push

- [PR #1](https://github.com/Soulbadguy54/RateApp/pull/1): карточка игры получает DB-детали, общий рейтинг, ссылки магазинов; оценки Rate APP и IGDB разделены.
- [PR #2](https://github.com/Soulbadguy54/RateApp/pull/2)–[PR #4](https://github.com/Soulbadguy54/RateApp/pull/4): системная защищённая «Хочу пройти», кнопка wishlist, поиск анонсированных игр и альтернативные имена.
- [PR #5](https://github.com/Soulbadguy54/RateApp/pull/5): вместо жёстко запрограммированных псевдонимов PostgreSQL `pg_trgm` и алиасы.
- [PR #6](https://github.com/Soulbadguy54/RateApp/pull/6)–[PR #8](https://github.com/Soulbadguy54/RateApp/pull/8): push о выходе игр, настройки на устройстве, первый opt-in и отделение wishlist от «Мои игры».
- [PR #9](https://github.com/Soulbadguy54/RateApp/pull/9)–[PR #11](https://github.com/Soulbadguy54/RateApp/pull/11): независимость коллекций от прохождений, переключение членства, цветовые темы и интерактивный emoji picker.
- [PR #12](https://github.com/Soulbadguy54/RateApp/pull/12)–[PR #15](https://github.com/Soulbadguy54/RateApp/pull/15): доработки карточек коллекций и toolbar, быстрого выбора членства, поиска/очистки, сортировки, удаления с подтверждением и анимаций.

## Долговременные ссылки / незакрытые вопросы

- [Импорт и пропущенные игры](docs/import-audit-2026-10-15.md): Stash Archived не считать автоматически оценёнными прохождениями.
- [Повторный аудит](docs/stability-audit-2026-10-16.md): внешний Sentry, Neon backup/PITR, защита main и release gate, Alembic baseline в production, Core Web Vitals/нагрузка. На 19 октября нет подтверждения, что внешняя эксплуатационная настройка завершена.
- [Регламент миграций](docs/DEPLOYMENT.md): резервная копия → отдельная проверка → Alembic → health/smoke → релиз.
