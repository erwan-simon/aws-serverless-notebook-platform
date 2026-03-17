window._authReady = (async function () {
  var TOKEN_KEY = "id_token";

  function generateRandomString(length) {
    var array = new Uint8Array(length);
    crypto.getRandomValues(array);
    return Array.from(array, function (b) {
      return b.toString(16).padStart(2, "0");
    }).join("");
  }

  async function sha256Base64url(plain) {
    var data = new TextEncoder().encode(plain);
    var hash = await crypto.subtle.digest("SHA-256", data);
    return btoa(String.fromCharCode.apply(null, new Uint8Array(hash)))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  }

  function getValidToken() {
    var token = localStorage.getItem(TOKEN_KEY);
    if (!token) return null;
    try {
      var parts = token.split(".");
      if (parts.length !== 3) return null;
      var payload = JSON.parse(
        atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"))
      );
      if (!payload.exp || payload.exp * 1000 < Date.now()) {
        localStorage.removeItem(TOKEN_KEY);
        return null;
      }
      return token;
    } catch (e) {
      localStorage.removeItem(TOKEN_KEY);
      return null;
    }
  }

  function haltNavigation() {
    // Return a promise that never resolves — the page is navigating away
    return new Promise(function () {});
  }

  // Step 1: Handle Cognito callback (authorization code in URL)
  var urlParams = new URLSearchParams(window.location.search);
  var code = urlParams.get("code");

  if (code) {
    var codeVerifier = sessionStorage.getItem("pkce_code_verifier");
    if (codeVerifier) {
      var response = await fetch(
        "https://" + CONFIG.cognitoDomain + "/oauth2/token",
        {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            grant_type: "authorization_code",
            client_id: CONFIG.cognitoClientId,
            redirect_uri: CONFIG.cognitoRedirectUri,
            code: code,
            code_verifier: codeVerifier,
          }),
        }
      );

      if (response.ok) {
        var tokens = await response.json();
        localStorage.setItem(TOKEN_KEY, tokens.id_token);
      }
      sessionStorage.removeItem("pkce_code_verifier");
    }

    var redirect = sessionStorage.getItem("auth_redirect") || "/";
    sessionStorage.removeItem("auth_redirect");
    window.location.replace(redirect);
    return haltNavigation();
  }

  // Step 2: Check for existing valid token
  var token = getValidToken();

  if (!token) {
    sessionStorage.setItem(
      "auth_redirect",
      window.location.pathname + window.location.search
    );

    var codeVerifier = generateRandomString(64);
    var codeChallenge = await sha256Base64url(codeVerifier);
    sessionStorage.setItem("pkce_code_verifier", codeVerifier);

    window.location.replace(
      "https://" +
        CONFIG.cognitoDomain +
        "/oauth2/authorize" +
        "?response_type=code" +
        "&client_id=" +
        encodeURIComponent(CONFIG.cognitoClientId) +
        "&redirect_uri=" +
        encodeURIComponent(CONFIG.cognitoRedirectUri) +
        "&code_challenge=" +
        encodeURIComponent(codeChallenge) +
        "&code_challenge_method=S256" +
        "&scope=openid"
    );
    return haltNavigation();
  }

  // Step 3: Token is valid — patch fetch to add Authorization header
  var originalFetch = window.fetch;
  window.fetch = function (url, options) {
    options = options || {};
    options.headers = options.headers || {};
    options.headers["Authorization"] = "Bearer " + token;
    return originalFetch.call(this, url, options);
  };
})();
