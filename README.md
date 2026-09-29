# 3dprinting

Сейчас в репозитории находится первый mobile-first прототип интерфейса каталога игр.

## Frontend

- React
- TypeScript
- Vite
- PWA (vite-plugin-pwa)
- mock-данные без backend

### Локальный запуск

    npm install
    npm run dev

### Production build

    npm run build

Результат сборки находится в dist/.

## Деплой на Cloudflare Pages

Репозиторий готов к Git integration:

- Production branch: main
- Build command: npm run build
- Build output directory: dist

После подключения репозитория Cloudflare Pages будет автоматически пересобирать тестовый сайт после push в main.

## Следующие этапы

Позже добавим Python/FastAPI backend, PostgreSQL и интеграцию с IGDB.
