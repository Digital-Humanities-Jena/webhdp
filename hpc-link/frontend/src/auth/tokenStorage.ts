const TOKEN_KEY = 'hpc_link_access_token';

export const getStoredAuthToken = () => {
  const sessionToken = window.sessionStorage.getItem(TOKEN_KEY);
  if (sessionToken) {
    return sessionToken;
  }

  // One-time migration from older persistent storage.
  const legacyToken = window.localStorage.getItem(TOKEN_KEY);
  if (legacyToken) {
    window.sessionStorage.setItem(TOKEN_KEY, legacyToken);
    window.localStorage.removeItem(TOKEN_KEY);
  }
  return legacyToken;
};

export const setStoredAuthToken = (token: string) => {
  window.sessionStorage.setItem(TOKEN_KEY, token);
  window.localStorage.removeItem(TOKEN_KEY);
};

export const clearStoredAuthToken = () => {
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(TOKEN_KEY);
};
