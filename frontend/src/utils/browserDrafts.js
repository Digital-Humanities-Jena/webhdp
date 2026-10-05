export function clearBrowserDrafts() {
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
    for (const key of keys) if (key?.startsWith('webhdp:metadata-draft:')) sessionStorage.removeItem(key)
  } catch { /* Storage may be disabled; sign-out must remain available. */ }
}
