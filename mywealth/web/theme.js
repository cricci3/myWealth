// Apply the last used theme before first render to avoid a light/dark flash.
// The setting itself lives in the database; localStorage is only a cache of it.
try {
  var t = localStorage.getItem('mw-theme');
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
} catch (e) {}
