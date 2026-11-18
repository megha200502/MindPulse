(() => {
  "use strict";
  if (!requireAuth()) return;
  renderNav("analytics");

  const root = document.getElementById("an-root");
  const C = { pine: "#21594A", sage: "#4C9A78", amber: "#E3B341", coral: "#D9534F", line: "#D6DED5", ink: "#4A5850" };
  const STRESS_COLORS = [C.sage, C.amber, "#C97C3B", C.coral];

  Chart.defaults.font.family = "'Inter', sans-serif";
  Chart.defaults.color = C.ink;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.maintainAspectRatio = false;

  const scaleY = (title, extra = {}) => ({ grid: { color: "#EEF2EE" }, border: { display: false }, title: { display: !!title, text: title }, ...extra });
  const scaleX = (title) => ({ grid: { display: false }, title: { display: !!title, text: title } });

  function card(cls, title, sub, id) {
    return `<div class="chart-card ${cls}"><h3>${title}</h3><p class="sub">${sub}</p><div class="chart-box"><canvas id="${id}"></canvas></div></div>`;
  }
  function kpi(label, value, unit = "", accent = false) {
    return `<div class="kpi${accent ? " accent" : ""}"><div class="k-label">${label}</div><div class="k-value">${value}<span class="k-unit">${unit}</span></div></div>`;
  }
  const fmt = (n) => Number(n).toLocaleString();

  // DB mein time UTC hota hai; yahan browser ke local timezone (IST) mein convert hota hai
  function toLocal(ts) {
    const d = new Date(String(ts).replace(" ", "T") + "Z");
    return d.toLocaleString(undefined, {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: true,
    });
  }

  function bar(id, g, { color = C.pine, horizontal = false, colors } = {}) {
    new Chart(document.getElementById(id), {
      type: "bar",
      data: { labels: g.labels, datasets: [{ data: g.avg, backgroundColor: colors || color, borderRadius: 6, maxBarThickness: 46 }] },
      options: {
        indexAxis: horizontal ? "y" : "x",
        scales: horizontal ? { x: scaleY("Avg score", { min: 0, max: 10 }), y: scaleX() } : { y: scaleY("Avg score", { min: 0, max: 10 }), x: scaleX() },
        plugins: { tooltip: { callbacks: { label: (c) => ` ${c.parsed[horizontal ? "x" : "y"]} avg  (${fmt(g.count[c.dataIndex])} students)` } } },
      },
    });
  }
  function line(id, g, xTitle) {
    new Chart(document.getElementById(id), {
      type: "line",
      data: { labels: g.labels, datasets: [{ data: g.avg, borderColor: C.pine, backgroundColor: "rgba(33,89,74,.12)", fill: true, tension: .3, pointRadius: 5, pointBackgroundColor: C.pine }] },
      options: {
        scales: { y: scaleY("Avg score", { min: 0, max: 10 }), x: scaleX(xTitle) },
        plugins: { tooltip: { callbacks: { label: (c) => ` ${c.parsed.y} avg  (${fmt(g.count[c.dataIndex])} students)` } } },
      },
    });
  }

  function drawCharts(a) {
    bar("c-stress", a.by_stress, { colors: STRESS_COLORS });
    line("c-screen", a.by_screen, "Daily screen time");
    line("c-sleep", a.by_sleep, "Sleep per night");
    line("c-activity", a.by_activity, "Physical activity per day");
    bar("c-platform", a.by_platform, { horizontal: true, color: C.sage });
    bar("c-country", a.by_country, { horizontal: true, color: C.pine });
    bar("c-academic", a.by_academic, { color: C.pine });
    bar("c-gender", a.by_gender, { color: C.sage });
    bar("c-purpose", a.by_purpose, { color: C.amber });

    new Chart(document.getElementById("c-dist"), {
      type: "bar",
      data: { labels: a.distribution.labels, datasets: [{ data: a.distribution.count, backgroundColor: C.pine, borderRadius: 4, categoryPercentage: 1, barPercentage: .92 }] },
      options: { scales: { y: scaleY("Students"), x: scaleX("Mental health score") } },
    });

    new Chart(document.getElementById("c-corr"), {
      type: "bar",
      data: { labels: a.correlation.labels, datasets: [{ data: a.correlation.value, backgroundColor: a.correlation.value.map((v) => (v >= 0 ? C.sage : C.coral)), borderRadius: 6 }] },
      options: { indexAxis: "y", scales: { x: scaleY("Correlation with score", { min: -1, max: 1 }), y: scaleX() }, plugins: { tooltip: { callbacks: { label: (c) => ` r = ${c.parsed.x}` } } } },
    });

    new Chart(document.getElementById("c-scatter"), {
      type: "scatter",
      data: { datasets: [{ data: a.scatter.screen, backgroundColor: "rgba(33,89,74,.45)", pointRadius: 3.5 }] },
      options: { scales: { x: scaleY("Daily screen time (hrs)", { grid: { display: false } }), y: scaleY("Score", { min: 3, max: 10 }) } },
    });
  }

  function historySection(rows) {
    if (!rows.length) {
      return `<p class="empty-note">No predictions yet. <a href="index.html">Run your first one</a> and it will show up here.</p>`;
    }
    const body = rows.map((r) => `<tr><td>${toLocal(r.created_at)}</td><td class="score">${r.score.toFixed(2)}</td><td>${r.screen ?? "-"} hrs</td><td>${r.sleep ?? "-"} hrs</td><td>${r.stress ?? "-"}</td></tr>`).join("");
    return `<div class="table-scroll"><table class="hist-table"><thead><tr><th>When</th><th>Score</th><th>Screen</th><th>Sleep</th><th>Stress</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }

  async function load() {
    try {
      const [aRes, hRes] = await Promise.all([apiFetch("/analytics"), apiFetch("/history")]);
      if (!aRes.ok) {
        const b = await aRes.json().catch(() => ({}));
        throw new Error(typeof b.detail === "string" ? b.detail : "Server returned " + aRes.status);
      }
      const a = await aRes.json();
      const hist = hRes.ok ? await hRes.json() : [];
      const k = a.kpis;

      root.innerHTML = `
        <div class="kpi-row">
          ${kpi("Students in dataset", fmt(k.students), "", true)}
          ${kpi("Average score", k.avg_score, "/10")}
          ${kpi("Avg screen time", k.avg_screen, "hrs")}
          ${kpi("Avg sleep", k.avg_sleep, "hrs")}
          ${kpi("Avg activity", k.avg_activity, "hrs")}
          ${kpi("High / very high stress", k.high_stress_pct, "%")}
        </div>

        <div class="chart-grid">
          ${card("wide", "Score distribution", "How many students fall in each score band", "c-dist")}
          ${card("", "Score by stress level", "Stress has the clearest step-down in scores", "c-stress")}
          ${card("", "What moves the score", "Correlation of each habit with mental health score", "c-corr")}
          ${card("third", "Screen time", "Avg score by daily hours", "c-screen")}
          ${card("third", "Sleep", "Avg score by hours per night", "c-sleep")}
          ${card("third", "Physical activity", "Avg score by hours per day", "c-activity")}
          ${card("wide", "Screen time vs score", "400 randomly sampled students, one dot each", "c-scatter")}
          ${card("", "Most-used platform", "Avg score by platform", "c-platform")}
          ${card("", "Top 8 countries by sample size", "Avg score by country", "c-country")}
          ${card("third", "Academic level", "Avg score", "c-academic")}
          ${card("third", "Gender", "Avg score", "c-gender")}
          ${card("third", "Purpose of use", "Avg score", "c-purpose")}
        </div>

        <h2 class="section-title">Your predictions</h2>
        <div class="chart-card wide">${historySection(hist)}</div>`;

      drawCharts(a);
    } catch (err) {
      root.innerHTML = `<div class="load-error">Couldn't load analytics: ${String(err.message).replace(/</g, "&lt;")}. Check that the API is running at ${API_BASE}.</div>`;
    }
  }
  load();
})();