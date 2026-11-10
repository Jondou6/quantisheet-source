// Offline cache for the app shell and the PDF viewer library.
// (Browsers only run service workers on https:// or localhost pages.)
const CACHE = 'quantisheet-v5';   // v5: attachments by header (Nov 6)
const MAX_ENTRIES = 60;   // keep the offline cache small
const ASSETS = ['./index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Project data (/hub/...: attachments, envelope pages, bid files) is
// private: it is never cached (review 3 #28).
function isPrivate(url) {
  try { return new URL(url).pathname.indexOf('/hub/') !== -1; } catch (e) { return true; }
}

async function trim(c) {
  const keys = await c.keys();
  for (let i = 0; i < keys.length - MAX_ENTRIES; i++) await c.delete(keys[i]);
}

// project.html posts {type: 'logout'} when someone signs out
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'logout') {
    e.waitUntil(caches.open(CACHE).then(async c => {
      for (const k of await c.keys()) if (isPrivate(k.url)) await c.delete(k);
    }));
  }
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (isPrivate(e.request.url)) return;          // straight to the network
  // network first, so a new version of the app is picked up; cache as fallback
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy).then(() => trim(c))).catch(() => {});
      }
      return res;
    }).catch(() =>
      caches.match(e.request).then(cached =>
        cached || new Response('Offline', { status: 503, statusText: 'Offline' }))
    )
  );
});
