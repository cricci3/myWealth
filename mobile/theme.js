// Apply the chosen theme before the first render (no light/dark flash). The preference is
// saved in IndexedDB; localStorage only caches it for this early, synchronous read.
try {
  var t = localStorage.getItem("mw-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}
