(function () {
  const ACCESS_TOKEN_KEY = "fragrantica_access_token";
  const REFRESH_TOKEN_KEY = "fragrantica_refresh_token";
  const EXPIRES_AT_KEY = "fragrantica_expires_at";
  const CODE_VERIFIER_KEY = "fragrantica_pkce_code_verifier";
  const RETURN_TO_KEY = "fragrantica_return_to";

  let configPromise = null;

  function base64UrlEncode(bytes) {
    const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join("");
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function randomString(length = 64) {
    const charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
    const values = new Uint8Array(length);
    crypto.getRandomValues(values);
    return Array.from(values, (value) => charset[value % charset.length]).join("");
  }

  async function sha256(value) {
    const data = new TextEncoder().encode(value);
    return new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  }

  async function getConfig() {
    if (!configPromise) {
      configPromise = fetch("/auth/config").then(async (response) => {
        const config = await response.json();
        if (!response.ok) throw new Error(config.error || "Could not load auth config");
        return config;
      });
    }

    return configPromise;
  }

  function loginUrl(config, codeChallenge) {
    const params = new URLSearchParams({
      client_id: config.clientId,
      redirect_uri: `${window.location.origin}/callback`,
      response_type: "code",
      scope: "openid profile email",
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
    });

    return `${config.keycloakUrl}/realms/${encodeURIComponent(config.realm)}/protocol/openid-connect/auth?${params}`;
  }

  function getAccessToken() {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }

  function isTokenUsable() {
    const token = getAccessToken();
    const expiresAt = Number(localStorage.getItem(EXPIRES_AT_KEY) || 0);
    return Boolean(token && Date.now() < expiresAt - 30000);
  }

  function storeTokens(tokens) {
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
    if (tokens.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    localStorage.setItem(EXPIRES_AT_KEY, String(Date.now() + Number(tokens.expires_in || 0) * 1000));
  }

  function clearTokens() {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(EXPIRES_AT_KEY);
    sessionStorage.removeItem(CODE_VERIFIER_KEY);
  }

  async function refreshAccessToken() {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) return false;

    const response = await fetch("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
      }),
    });

    if (!response.ok) {
      clearTokens();
      return false;
    }

    storeTokens(await response.json());
    return true;
  }

  async function ensureToken() {
    if (isTokenUsable()) return true;
    return refreshAccessToken();
  }

  async function authHeaders(headers = {}) {
    if (!(await ensureToken())) return headers;
    return { ...headers, Authorization: `Bearer ${getAccessToken()}` };
  }

  async function authFetch(url, options = {}) {
    const headers = await authHeaders(options.headers || {});
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
      clearTokens();
      window.location.href = `/login?return_to=${encodeURIComponent(window.location.pathname)}`;
    }
    return response;
  }

  async function requireAuth() {
    if (await ensureToken()) return true;
    window.location.href = `/login?return_to=${encodeURIComponent(window.location.pathname)}`;
    return false;
  }

  async function startLogin(returnTo = "/") {
    const config = await getConfig();
    const verifier = randomString();
    const challenge = base64UrlEncode(await sha256(verifier));
    sessionStorage.setItem(CODE_VERIFIER_KEY, verifier);
    sessionStorage.setItem(RETURN_TO_KEY, returnTo || "/");
    window.location.href = loginUrl(config, challenge);
  }

  async function completeLogin(code) {
    const verifier = sessionStorage.getItem(CODE_VERIFIER_KEY);
    if (!verifier) throw new Error("Missing login verifier. Please start login again.");

    const response = await fetch("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "authorization_code",
        code,
        code_verifier: verifier,
        redirect_uri: `${window.location.origin}/callback`,
      }),
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Login failed");

    storeTokens(data);
    sessionStorage.removeItem(CODE_VERIFIER_KEY);
    const returnTo = sessionStorage.getItem(RETURN_TO_KEY) || "/";
    sessionStorage.removeItem(RETURN_TO_KEY);
    window.location.href = returnTo;
  }

  async function logout() {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    clearTokens();
    if (refreshToken) {
      try {
        await fetch("/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      } catch (_e) {
        // Ignore errors, tokens are already cleared
      }
    }
    window.location.href = "/login";
  }

  window.Auth = {
    authFetch,
    authHeaders,
    clearTokens,
    completeLogin,
    getConfig,
    logout,
    requireAuth,
    startLogin,
  };
})();
