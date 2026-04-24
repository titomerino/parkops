const CACHE_NAME = 'parkops-v1';
const urlsToCache = [
  '/',
  '/static/bootstrap/css/bootstrap.min.css',
  '/static/htmx/htmx.min.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});