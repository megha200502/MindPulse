const API_BASE = " https://mindpulse-jvjv.onrender.com"; // change to your Render URL when deploying

const Auth = {
  token: () => localStorage.getItem("mp_token"),
  user: () => { try { return JSON.parse(localStorage.getItem("mp_user")); } catch { return null; } },
  save(data) {
    localStorage.setItem("mp_token", data.token);
    localStorage.setItem("mp_user", JSON.stringify(data.user));
  },
  clear() { localStorage.removeItem("mp_token"); localStorage.removeItem("mp_user"); },
};

function requireAuth() {
  if (!Auth.token()) { window.location.replace("login.html"); return false; }
  return true;
}

function redirectIfLoggedIn() {
  if (Auth.token()) window.location.replace("index.html");
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (Auth.token()) headers["Authorization"] = "Bearer " + Auth.token();
  const res = await fetch(API_BASE + path, { ...options, headers });
  if (res.status === 401 && !path.startsWith("/login")) {
    Auth.clear();
    window.location.replace("login.html");
  }
  return res;
}

async function logout() {
  try { await apiFetch("/logout", { method: "POST" }); } catch (_) {}
  Auth.clear();
  window.location.replace("login.html");
}

function renderNav(active) {
  const root = document.getElementById("nav-root");
  if (!root) return;
  const u = Auth.user();
  const link = (href, key, label) =>
    `<a href="${href}" class="nav-link${active === key ? " active" : ""}">${label}</a>`;
  root.innerHTML = `
    <nav class="topnav">
      <a href="index.html" class="brand">MindPulse</a>
      <div class="nav-links">
        ${link("index.html", "predict", "Predict")}
        ${link("analytics.html", "analytics", "Analytics")}
      </div>
      <div class="nav-user">
        <span class="nav-name">${u ? u.name.replace(/</g, "&lt;") : ""}</span>
        <button type="button" class="nav-logout" id="logout-btn">Log out</button>
      </div>
    </nav>`;
  document.getElementById("logout-btn").addEventListener("click", logout);
}