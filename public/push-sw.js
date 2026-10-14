/* Imported by the generated Workbox service worker; handles background pushes. */
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = {}; }
  const title = typeof data.title === 'string' ? data.title : 'RateApp';
  const body = typeof data.body === 'string' ? data.body : 'Новая игровая новость';
  const path = typeof data.url === 'string' ? data.url : '/';
  const target = new URL(path, self.location.origin);
  const safeUrl = target.origin === self.location.origin ? target.pathname + target.search : '/';
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/icon.svg',
    badge: '/icon.svg',
    tag: typeof data.tag === 'string' ? data.tag : 'rateapp-release',
    data: { url: safeUrl },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || '/', self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    const tabs = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const existing = tabs.find(tab => new URL(tab.url).origin === self.location.origin);
    if (existing) {
      await existing.navigate(url.href);
      await existing.focus();
    } else {
      await self.clients.openWindow(url.href);
    }
  })());
});
