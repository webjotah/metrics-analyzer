// Frontend JavaScript para o Running Metrics Analyzer — Amazfit Active 2

let currentWorkoutId = null;
let currentWorkoutData = null;
let chatHistory = [];
let pendingUploadFiles = [];

document.addEventListener("DOMContentLoaded", async () => {
  await loadProfile();
  await refreshWorkoutsList();
});

function switchTab(tabName) {
  document.querySelectorAll(".view-section").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach((el) => el.classList.remove("active"));

  const targetSection = document.getElementById(`tab-${tabName}`);
  if (targetSection) targetSection.classList.add("active");

  const btns = document.querySelectorAll(".nav-btn");
  const mapIdx = { workout: 0, upload: 1, evolution: 2, profile: 3 };
  if (btns[mapIdx[tabName]]) btns[mapIdx[tabName]].classList.add("active");

  if (tabName === "evolution") {
    loadEvolutionView();
  }
}

async function refreshWorkoutsList(selectId = null, reloadDetail = true) {
  const res = await fetch("/api/workouts");
  const data = await res.json();
  const listEl = document.getElementById("sidebar-workout-list");
  listEl.innerHTML = "";

  const workouts = data.workouts || [];
  if (workouts.length === 0) {
    listEl.innerHTML = `<p style="font-size:12px; color:#94a3b8;">Nenhum treino no banco ainda.</p>`;
    return;
  }

  const idToSelect = selectId || currentWorkoutId || workouts[0].workout_id;

  workouts.forEach((w) => {
    const item = document.createElement("div");
    item.className = `workout-item ${w.workout_id === idToSelect ? "selected" : ""}`;
    const dateStr = (w.start_time_iso || "").replace("T", " ").slice(0, 16);
    const aiBadge = w.has_ai_report ? `<span class="badge badge-orange" style="font-size:9px; padding:1px 5px;">IA REPORT</span>` : "";

    item.innerHTML = `
      <div class="workout-item-header">
        <span>${dateStr}</span>
        ${aiBadge}
      </div>
      <div class="workout-item-title">${w.workout_type}</div>
      <div class="workout-item-stats">
        <span><svg class="icon icon-sm" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> ${w.total_distance_km} km</span>
        <span><svg class="icon icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${w.avg_pace_min_km}/km</span>
        <span><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg> ${w.avg_hr_bpm || "-"} bpm</span>
      </div>
    `;
    item.onclick = () => {
      switchTab("workout");
      loadWorkoutDetail(w.workout_id);
    };
    listEl.appendChild(item);
  });

  if (reloadDetail) {
    await loadWorkoutDetail(idToSelect);
  }
}

async function loadWorkoutDetail(workoutId) {
  currentWorkoutId = workoutId;
  chatHistory = [];
  document.getElementById("chat-messages").innerHTML = "";

  // Atualiza destaque na sidebar
  document.querySelectorAll(".workout-item").forEach((el) => el.classList.remove("selected"));

  const res = await fetch(`/api/workout?id=${encodeURIComponent(workoutId)}`);
  const data = await res.json();
  if (data.error) return;

  currentWorkoutData = data;
  const wjson = data.workout_json;
  const meta = wjson.metadata || {};
  const sum = wjson.summary || {};
  const phys = wjson.physiology || {};
  const bio = wjson.biomechanics_running_dynamics || {};
  const pauses = wjson.pauses_analysis || {};
  const userCtx = meta.user_context || {};

  document.getElementById("w-title").textContent = `${meta.workout_type_confirmed || meta.workout_type_detected} — ${sum.total_distance_km} km`;
  const rpeText = userCtx.rpe_effort_1_to_10 ? ` | Esforço Percebido (RPE): ${userCtx.rpe_effort_1_to_10}/10` : "";
  const notesText = userCtx.weather_or_notes ? ` | Notas: "${userCtx.weather_or_notes}"` : "";
  document.getElementById("w-subtitle").textContent = `Data: ${(meta.date || "").replace("T", " ")} (${meta.day_of_week || ""})${rpeText}${notesText}`;
  document.getElementById("w-type-badge").textContent = meta.workout_type_confirmed || meta.workout_type_detected;

  // Preenche editor de contexto
  document.getElementById("edit-workout-type").value = meta.workout_type_confirmed || "Rodagem (5 km)";
  document.getElementById("edit-rpe").value = userCtx.rpe_effort_1_to_10 || "";
  document.getElementById("edit-notes").value = userCtx.weather_or_notes || "";

  renderDidacticCards(sum, phys, bio, data.timeseries || []);
  renderBlocksAndPausesTables(wjson.active_blocks_or_intervals || [], pauses);
  renderWorkoutCharts(data.timeseries || [], wjson.splits_per_km || [], phys.hr_zones_time_sec || {});

  // Relatório IA em cache (se já existir)
  const reportContainer = document.getElementById("ai-report-container");
  const toolsIndicator = document.getElementById("ai-tools-indicator");
  const expandBar = document.getElementById("ai-expand-bar");
  toolsIndicator.style.display = "none";
  if (data.ai_report_md) {
    reportContainer.innerHTML = marked.parse(data.ai_report_md);
    reportContainer.classList.add("collapsed");
    if (expandBar) expandBar.style.display = data.ai_report_md.length > 500 ? "flex" : "none";
  } else {
    reportContainer.classList.remove("collapsed");
    reportContainer.innerHTML = `<p style="color:var(--text-muted);">Este treino ainda não tem análise salva no banco. Clique em <strong>"Gerar Análise"</strong> acima para o Gemini processar os dados deste treino e compará-lo com seu histórico no banco SQLite.</p>`;
    if (expandBar) expandBar.style.display = "none";
  }
}

function generateSparklineSvg(dataPoints, strokeColor, isInverse = false) {
  if (!dataPoints || dataPoints.length < 2) return "";
  const width = 105;
  const height = 30;
  const padding = 2;

  const valid = dataPoints.filter((v) => v !== null && !isNaN(v) && v > 0);
  if (valid.length < 2) return "";

  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const range = max - min || 1;

  // Downsample to max 24 points for crisp rendering
  const step = Math.max(1, Math.floor(valid.length / 24));
  const sampled = [];
  for (let i = 0; i < valid.length; i += step) {
    sampled.push(valid[i]);
  }
  if (sampled[sampled.length - 1] !== valid[valid.length - 1]) {
    sampled.push(valid[valid.length - 1]);
  }

  const n = sampled.length;
  const pts = sampled.map((val, i) => {
    const x = padding + (i / (n - 1)) * (width - 2 * padding);
    let norm = (val - min) / range;
    if (isInverse) norm = 1 - norm; // Pace: lower is faster
    const y = height - padding - norm * (height - 2 * padding);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const pathD = `M ${pts.join(" L ")}`;
  const areaD = `M ${pts[0]} L ${pts.join(" L ")} L ${pts[pts.length - 1].split(",")[0]},${height} L ${pts[0].split(",")[0]},${height} Z`;
  const gradId = `spark-${Math.random().toString(36).substr(2, 8)}`;

  return `
    <svg class="sparkline-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${strokeColor}" stop-opacity="0.25" />
          <stop offset="100%" stop-color="${strokeColor}" stop-opacity="0.0" />
        </linearGradient>
      </defs>
      <path d="${areaD}" fill="url(#${gradId})" />
      <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  `;
}

function renderDidacticCards(sum, phys, bio, timeseries = []) {
  const grid = document.getElementById("didactic-metrics-grid");

  // Avaliações didáticas automáticas
  const cad = bio.avg_cadence_spm || 0;
  const cadBadge = cad >= 168 ? ["Ótima Eficiência", "badge-good"] : ["Pode Aumentar", "badge-warn"];

  const vr = bio.avg_vertical_ratio_pct || 0;
  const vrBadge = vr <= 7.0 ? ["Excelente (<7%)", "badge-good"] : vr <= 8.5 ? ["Normal", "badge-info"] : ["Salto Alto", "badge-warn"];

  const gct = bio.avg_ground_contact_time_ms || 0;
  const gctBadge = gct <= 270 ? ["Passada Reativa", "badge-good"] : ["Contato Longo", "badge-info"];

  const drift = phys.cardiac_drift_pct;
  const driftBadge = drift !== null && drift <= 5.0 ? ["Base Sólida", "badge-good"] : ["Fadiga / Calor", "badge-warn"];

  // Vetores de dados para as micro-sparklines
  const paceSeries = timeseries.map((r) => (r.speed_mps && r.speed_mps > 0.8 ? 1000 / r.speed_mps : null));
  const hrSeries = timeseries.map((r) => r.heart_rate_bpm);
  const cadSeries = timeseries.map((r) => r.cadence_spm);
  const vrSeries = timeseries.map((r) => r.vertical_oscillation_mm);
  const pwrSeries = timeseries.map((r) => r.power_watts);

  const cards = [
    {
      title: "Pace & Tempo Ativo",
      icon: `<svg class="icon" style="stroke:var(--orange-primary);" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
      badge: [`Total: ${sum.total_elapsed_formatted}`, "badge-neutral"],
      value: `${sum.avg_pace_min_km} <span style="font-size:14px; color:var(--text-muted); font-weight:500;">/km</span>`,
      sparkline: generateSparklineSvg(paceSeries, "#ff5500", true),
      sub: `Tempo correndo: <strong>${sum.active_timer_formatted}</strong> &bull; Máx: ${sum.max_pace_min_km}/km`,
    },
    {
      title: "Frequência Cardíaca",
      icon: `<svg class="icon" style="stroke:var(--coral-primary);" viewBox="0 0 24 24"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>`,
      badge: [`Máx: ${phys.max_hr_bpm} bpm`, "badge-neutral"],
      value: `${phys.avg_hr_bpm} <span style="font-size:14px; color:var(--text-muted); font-weight:500;">bpm</span>`,
      sparkline: generateSparklineSvg(hrSeries, "#f43f5e"),
      sub: `TE Aeróbico: <strong>${phys.training_effect_aerobic}</strong> &bull; Anaeróbico: <strong>${phys.training_effect_anaerobic}</strong>`,
    },
    {
      title: "Deriva Cardíaca (Drift)",
      icon: `<svg class="icon" style="stroke:var(--cyan-primary);" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
      badge: driftBadge,
      value: drift !== null ? `${drift > 0 ? "+" : ""}${drift}%` : "N/A",
      sparkline: generateSparklineSvg(hrSeries, "#38bdf8"),
      sub: `Estabilidade cardiovascular na 2ª metade do treino`,
    },
    {
      title: "Cadência & Passada",
      icon: `<svg class="icon" style="stroke:var(--violet-primary);" viewBox="0 0 24 24"><path d="M13 4a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"/><path d="m10 17 3-3-2-4 4-2 3 3"/><path d="M5 21l5-4"/><path d="M14 14l-2 7"/></svg>`,
      badge: cadBadge,
      value: `${cad} <span style="font-size:14px; color:var(--text-muted); font-weight:500;">spm</span>`,
      sparkline: generateSparklineSvg(cadSeries, "#818cf8"),
      sub: `Passada média: <strong>${bio.avg_step_length_m} m</strong> &bull; Máx: ${bio.max_cadence_spm} spm`,
    },
    {
      title: "Razão & Oscilação Vertical",
      icon: `<svg class="icon" style="stroke:var(--amber-primary);" viewBox="0 0 24 24"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
      badge: vrBadge,
      value: `${vr}% <span style="font-size:14px; color:var(--text-muted); font-weight:500;">(${bio.avg_vertical_oscillation_cm} cm)</span>`,
      sparkline: generateSparklineSvg(vrSeries, "#f59e0b"),
      sub: `Eficiência vertical &bull; Menor razão = passada mais econômica`,
    },
    {
      title: "Potência & Tempo de Solo",
      icon: `<svg class="icon" style="stroke:var(--green-primary);" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
      badge: gctBadge,
      value: `${bio.avg_power_watts} W <span style="font-size:14px; color:var(--text-muted); font-weight:500;">| ${gct} ms</span>`,
      sparkline: generateSparklineSvg(pwrSeries, "#10b981"),
      sub: `Potência máx: <strong>${bio.max_power_watts} W</strong> &bull; Ganho: +${sum.elevation_gain_m}m`,
    },
  ];

  grid.innerHTML = cards
    .map(
      (c) => `
    <div class="metric-card">
      <div class="metric-header">
        <span>${c.icon} ${c.title}</span>
        <span class="badge ${c.badge[1]}">${c.badge[0]}</span>
      </div>
      <div class="metric-body">
        <div class="metric-value">${c.value}</div>
        ${c.sparkline || ""}
      </div>
      <div class="metric-sub">${c.sub}</div>
    </div>
  `
    )
    .join("");
}

function renderBlocksAndPausesTables(blocks, pauses) {
  document.getElementById("blocks-count-badge").textContent = `${blocks.length} bloco(s)`;

  // Segmented Equalizer Matrix (Inspo1.webp)
  const equalizer = document.getElementById("blocks-equalizer");
  if (equalizer) {
    if (blocks && blocks.length > 0) {
      equalizer.style.display = "flex";
      equalizer.innerHTML = blocks
        .map((b) => {
          const hr = b.avg_hr_bpm || 150;
          let zClass = "active-z3";
          if (hr < 135) zClass = "active-z1";
          else if (hr < 150) zClass = "active-z2";
          else if (hr < 165) zClass = "active-z3";
          else if (hr < 178) zClass = "active-z4";
          else zClass = "active-z5";

          // Calculate 1 to 5 active segments
          const activeCount = Math.min(5, Math.max(1, Math.round((b.speed_mps || 3.0) / 0.85)));
          let segments = "";
          for (let i = 1; i <= 5; i++) {
            const active = i <= activeCount ? zClass : "";
            segments += `<div class="equalizer-segment ${active}"></div>`;
          }

          return `
            <div class="equalizer-col" title="Bloco #${b.block_number}: ${b.distance_m}m em ${b.pace_min_km}/km (FC ${b.avg_hr_bpm} bpm)">
              <div class="equalizer-bars">${segments}</div>
              <div class="equalizer-val">${b.pace_min_km}</div>
              <div class="equalizer-label">#${b.block_number} &bull; ${b.distance_m}m</div>
            </div>
          `;
        })
        .join("");
    } else {
      equalizer.style.display = "none";
    }
  }

  const blocksBody = document.querySelector("#blocks-table tbody");
  blocksBody.innerHTML = blocks
    .map(
      (b) => `
    <tr>
      <td><strong style="color:var(--orange-primary);">#${b.block_number}</strong></td>
      <td><strong>${b.distance_m} m</strong></td>
      <td>${b.duration_formatted}</td>
      <td><strong style="color:var(--text-hero);">${b.pace_min_km}/km</strong></td>
      <td>${b.avg_hr_bpm} / ${b.max_hr_bpm} bpm</td>
      <td>${b.avg_power_w || "-"} W</td>
      <td>${b.avg_cadence_spm || "-"} spm</td>
      <td>${b.avg_step_length_m || "-"} m</td>
      <td>${b.avg_ground_contact_ms || "-"} ms</td>
    </tr>
  `
    )
    .join("");

  const sem = pauses.traffic_lights_under_60s || { count: 0, total_time_sec: 0 };
  const rest = pauses.rest_stops_over_60s || { count: 0, total_time_sec: 0, stops: [] };

  document.getElementById("pauses-badge").textContent = `${sem.count} semáforo(s) filtrado(s)`;
  document.getElementById("pauses-summary-text").innerHTML = `
    Semáforos / Trânsito (&le; 60s): <strong style="color:var(--text-hero);">${sem.count} parada(s)</strong> (${sem.total_time_sec}s somados) &bull;
    Descansos Reais (&gt; 60s): <strong style="color:var(--orange-primary);">${rest.count} parada(s)</strong> (${Math.round(rest.total_time_sec / 60)} min / ${rest.total_time_sec}s).
  `;

  const pausesBody = document.querySelector("#pauses-table tbody");
  if (!rest.stops || rest.stops.length === 0) {
    pausesBody.innerHTML = `<tr><td colspan="6" style="color:var(--text-muted);">Nenhuma parada de descanso &gt; 60s registrada nesta sessão.</td></tr>`;
  } else {
    pausesBody.innerHTML = rest.stops
      .map(
        (s, idx) => `
      <tr>
        <td><strong style="color:var(--orange-primary);">#${idx + 1}</strong></td>
        <td>Km ${s.after_km}</td>
        <td>${s.duration_formatted} (${s.duration_sec}s)</td>
        <td>${s.hr_at_stop || "-"} bpm</td>
        <td>${s.hr_at_resume || "-"} bpm</td>
        <td>
          <span class="recovery-drop-meter">
            <svg class="icon icon-sm" style="stroke:#10b981;" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
            -${s.hr_recovery_drop !== null ? s.hr_recovery_drop : 0} bpm
          </span>
        </td>
      </tr>
    `
      )
      .join("");
  }
}

function renderWorkoutCharts(timeseries, splits, hrZones) {
  // 1. Gráfico de Série Temporal Sincronizada (Distância no eixo X)
  const validRecs = timeseries.filter((r) => r.distance_m !== null && r.speed_mps !== null && r.speed_mps > 0.8);
  const xKm = validRecs.map((r) => +(r.distance_m / 1000.0).toFixed(2));
  const yHr = validRecs.map((r) => r.heart_rate_bpm);
  const yPaceDecimal = validRecs.map((r) => {
    const secPerKm = 1000.0 / r.speed_mps;
    return Math.min(10.0, +(secPerKm / 60.0).toFixed(2));
  });
  const yAlt = validRecs.map((r) => r.altitude_m);
  const yCad = validRecs.map((r) => r.cadence_spm);

  const traceHr = {
    x: xKm,
    y: yHr,
    name: "FC (bpm)",
    type: "scatter",
    mode: "lines",
    line: { color: "#f43f5e", width: 2 },
    yaxis: "y1",
  };
  const tracePace = {
    x: xKm,
    y: yPaceDecimal,
    name: "Pace (min/km)",
    type: "scatter",
    mode: "lines",
    line: { color: "#ff5500", width: 2.2 },
    yaxis: "y2",
  };
  const traceCad = {
    x: xKm,
    y: yCad,
    name: "Cadência (spm)",
    type: "scatter",
    mode: "lines",
    line: { color: "#818cf8", width: 1.5, dash: "dot" },
    yaxis: "y1",
  };
  const traceAlt = {
    x: xKm,
    y: yAlt,
    name: "Altitude (m)",
    type: "scatter",
    mode: "lines",
    fill: "tozeroy",
    fillcolor: "rgba(255, 85, 0, 0.05)",
    line: { color: "#64748b", width: 1 },
    yaxis: "y3",
  };

  const layoutTs = {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "#94a3b8", family: "'Plus Jakarta Sans', sans-serif", size: 11 },
    margin: { l: 48, r: 56, t: 20, b: 36 },
    hovermode: "x unified",
    legend: { orientation: "h", y: 1.12 },
    xaxis: { title: "Distância (km)", gridcolor: "#1c1e28", zerolinecolor: "#1c1e28" },
    yaxis: { title: "FC (bpm) / Cadência (spm)", gridcolor: "#1c1e28", zerolinecolor: "#1c1e28" },
    yaxis2: {
      title: "Pace (min/km - invertido)",
      overlaying: "y",
      side: "right",
      autorange: "reversed",
      showgrid: false,
    },
    yaxis3: {
      overlaying: "y",
      visible: false,
    },
  };
  Plotly.newPlot("chart-timeseries", [traceAlt, tracePace, traceCad, traceHr], layoutTs, { responsive: true });

  // 2. Gráfico de Splits por Km
  const kmLabels = splits.map((s) => `Km ${s.km}`);
  const splitPaceMin = splits.map((s) => {
    if (!s.pace_min_km) return 0;
    const [m, sec] = s.pace_min_km.split(":").map(Number);
    return +(m + sec / 60.0).toFixed(2);
  });
  const splitHr = splits.map((s) => s.avg_hr_bpm);

  Plotly.newPlot(
    "chart-splits",
    [
      {
        x: kmLabels,
        y: splitPaceMin,
        text: splits.map((s) => `${s.pace_min_km}/km`),
        textposition: "auto",
        name: "Pace (min/km)",
        type: "bar",
        marker: { color: "#ff5500" },
      },
      {
        x: kmLabels,
        y: splitHr,
        name: "FC Média (bpm)",
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#f43f5e", width: 2.2 },
      },
    ],
    {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: "#94a3b8", family: "'Plus Jakarta Sans', sans-serif", size: 11 },
      margin: { l: 45, r: 45, t: 20, b: 35 },
      legend: { orientation: "h", y: 1.15 },
      yaxis: { title: "Pace (min/km)", gridcolor: "#1c1e28", zerolinecolor: "#1c1e28" },
      yaxis2: { title: "FC (bpm)", overlaying: "y", side: "right", showgrid: false },
    },
    { responsive: true }
  );

  // 3. Gráfico de Zonas de FC
  const zoneNames = ["Z1 Recuperação", "Z2 Base Aeróbica", "Z3 Ritmo", "Z4 Limiar", "Z5 Máximo"];
  const zoneSecs = [
    hrZones.z1_warmup || 0,
    hrZones.z2_fat_burn || 0,
    hrZones.z3_aerobic || 0,
    hrZones.z4_threshold || 0,
    hrZones.z5_anaerobic_max || 0,
  ];
  const zoneMins = zoneSecs.map((s) => +(s / 60.0).toFixed(1));

  Plotly.newPlot(
    "chart-zones",
    [
      {
        x: zoneNames,
        y: zoneMins,
        text: zoneMins.map((m) => `${m} min`),
        textposition: "auto",
        type: "bar",
        marker: {
          color: ["#38bdf8", "#10b981", "#eab308", "#ff5500", "#ef4444"],
        },
      },
    ],
    {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: "#94a3b8", family: "'Plus Jakarta Sans', sans-serif", size: 11 },
      margin: { l: 45, r: 20, t: 20, b: 35 },
      yaxis: { title: "Tempo (minutos)", gridcolor: "#1c1e28", zerolinecolor: "#1c1e28" },
    },
    { responsive: true }
  );
}

function toggleContextEditor() {
  const el = document.getElementById("context-editor-card");
  el.style.display = el.style.display === "none" ? "block" : "none";
}

async function saveWorkoutContext() {
  if (!currentWorkoutId) return;
  const workout_type_confirmed = document.getElementById("edit-workout-type").value;
  const rpe_effort = document.getElementById("edit-rpe").value;
  const weather_or_notes = document.getElementById("edit-notes").value;

  const res = await fetch("/api/update_workout_context", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workout_id: currentWorkoutId,
      workout_type_confirmed,
      rpe_effort: rpe_effort ? Number(rpe_effort) : null,
      weather_or_notes,
    }),
  });
  const data = await res.json();
  if (data.ok) {
    document.getElementById("context-editor-card").style.display = "none";
    await refreshWorkoutsList(data.workout_id);
  }
}

function toggleReportExpansion() {
  const box = document.getElementById("ai-report-container");
  const text = document.getElementById("text-toggle-report");
  const icon = document.getElementById("icon-toggle-report");
  if (!box) return;
  const isCollapsed = box.classList.contains("collapsed");
  if (isCollapsed) {
    box.classList.remove("collapsed");
    if (text) text.textContent = "Recolher Relatório";
    if (icon) icon.innerHTML = `<polyline points="18 15 12 9 6 15"/>`;
  } else {
    box.classList.add("collapsed");
    if (text) text.textContent = "Ver Relatório Completo";
    if (icon) icon.innerHTML = `<polyline points="6 9 12 15 18 9"/>`;
  }
}

function askQuickPrompt(questionText) {
  const chatInput = document.getElementById("chat-input");
  if (!chatInput) return;
  chatInput.value = questionText;
  sendChatMessage();
  const chatSection = document.getElementById("chat-section");
  if (chatSection) {
    chatSection.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

async function generateAIReport(force = false) {
  if (!currentWorkoutId) return;
  const btn = document.getElementById("btn-generate-ai");
  const btnRegen = document.getElementById("btn-regenerate-ai");
  const container = document.getElementById("ai-report-container");
  const toolsIndicator = document.getElementById("ai-tools-indicator");
  const expandBar = document.getElementById("ai-expand-bar");

  btn.disabled = true;
  btnRegen.disabled = true;
  if (expandBar) expandBar.style.display = "none";
  container.classList.remove("collapsed");
  toolsIndicator.style.display = "block";
  toolsIndicator.textContent = "⏳ Conectando ao Treinador IA e preparando histórico do SQLite...";
  container.innerHTML = `<p style="color:#38bdf8;">⏳ O Treinador IA está analisando as métricas deste treino e consultando seus treinos anteriores no banco SQLite... O texto aparecerá ao vivo abaixo assim que a 1ª frase ficar pronta (~6 a 10s)!</p>`;

  console.log(
    `%c🤖 [GeminiCoach] Iniciando geração de relatório (workout_id=${currentWorkoutId}, force_regenerate=${force})...`,
    "color: #38bdf8; font-weight: bold;"
  );

  let accumulatedMd = "";
  let firstChunkLogged = false;

  try {
    const res = await fetch("/api/analyze_ai_stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workout_id: currentWorkoutId, force }),
    });

    if (!res.ok || !res.body) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let sseBuffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      sseBuffer += decoder.decode(value, { stream: true });
      const parts = sseBuffer.split("\n\n");
      sseBuffer = parts.pop() || "";

      for (const block of parts) {
        const line = block.trim();
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.slice(5).trim();
        if (!jsonStr) continue;

        let ev;
        try {
          ev = JSON.parse(jsonStr);
        } catch (e) {
          continue;
        }

        if (ev.type === "status") {
          console.log(`%c🤖 [GeminiCoach] Status: ${ev.message}`, "color: #94a3b8;");
          toolsIndicator.textContent = `⏳ ${ev.message}`;
        } else if (ev.type === "model_selected") {
          const roleTag = ev.from_cache
            ? "⚡ Cache SQLite"
            : ev.used_fallback
            ? "⚠️ Modelo Fallback"
            : "✅ Modelo Principal";
          const ipInfo = ev.dns_tcp_ms ? ` (TCP: ${ev.dns_tcp_ms}ms)` : "";
          console.log(
            `%c🤖 [GeminiCoach] Modelo ativo selecionado: ${ev.model_used} (${roleTag})${ipInfo}`,
            "color: #38bdf8; font-weight: bold;",
            ev
          );
          toolsIndicator.textContent = `🧠 Modelo respondendo: ${ev.model_used} (${roleTag}) | 🛠️ SQLite: ${(ev.tools_called || []).join(" | ")} — preparando raciocínio...`;
        } else if (ev.type === "thinking_start") {
          console.log(
            `%c🧠 [GeminiCoach] 1º token de raciocínio interno (Thinking) recebido em ${ev.first_thought_sec}s! Modelo analisando métricas...`,
            "color: #38bdf8; font-weight: bold;"
          );
          toolsIndicator.textContent = `🧠 [Thinking] ${ev.model_used} raciocinando sobre suas métricas... (1º pensamento em ${ev.first_thought_sec}s)`;
        } else if (ev.type === "thinking_chunk") {
          toolsIndicator.textContent = `🧠 [Thinking] Analisando métricas e histórico no SQLite... (${ev.elapsed_sec}s | pensamento #${ev.thought_index})`;
        } else if (ev.type === "thinking_done") {
          console.log(
            `%c✍️ [GeminiCoach] Raciocínio finalizado (${ev.thinking_duration_sec}s, ${ev.thought_chunks_count} blocos)! Iniciando escrita do relatório em ${ev.ttft_sec}s...`,
            "color: #a855f7; font-weight: bold;"
          );
          toolsIndicator.textContent = `✍️ Raciocínio concluído (${ev.thinking_duration_sec}s)! Escrevendo relatório na tela...`;
        } else if (ev.type === "chunk") {
          if (!firstChunkLogged) {
            firstChunkLogged = true;
            console.log(
              `%c⚡ [GeminiCoach] 1º pedaço de texto visível recebido de [${ev.model_used}] em ${ev.ttft_sec}s (TTFT)! Transmitindo ao vivo na tela...`,
              "color: #22c55e; font-weight: bold;"
            );
          }
          accumulatedMd += ev.text || "";
          container.innerHTML = marked.parse(accumulatedMd);
        } else if (ev.type === "done") {
          const finalMd = ev.ai_report_md || accumulatedMd;
          container.innerHTML = marked.parse(finalMd);
          const expandBar = document.getElementById("ai-expand-bar");
          if (expandBar) {
            expandBar.style.display = finalMd.length > 500 ? "flex" : "none";
          }
          container.classList.add("collapsed");
          const roleTag = ev.from_cache
            ? "Cache SQLite"
            : ev.used_fallback
            ? "Fallback Ativado"
            : "Modelo Principal";
          const timingDetail = ev.from_cache
            ? "0.0s (Instantâneo)"
            : `${ev.elapsed_sec}s (HTTP: ${ev.http_connect_sec || 0}s | Pensou: ${ev.thinking_duration_sec || 0}s | Escreveu: ${ev.generation_duration_sec || 0}s)`;
          toolsIndicator.style.display = "block";
          toolsIndicator.textContent = `🧠 Respondido por: ${ev.model_used} (${roleTag}) | ⏱️ Tempo: ${timingDetail} | 🛠️ SQLite: ${(ev.tools_called || []).join(" | ")}`;

          console.log(
            `%c✅ [GeminiCoach] Relatório finalizado! Modelo que respondeu: ${ev.model_used} (${roleTag}) | Tempo total: ${ev.elapsed_sec}s | TTFT: ${ev.ttft_sec}s`,
            "color: #22c55e; font-weight: bold; font-size: 13px;"
          );
          console.table({
            "1_modelo_que_respondeu": ev.model_used,
            "2_usou_fallback": ev.used_fallback ? "SIM (Fallback)" : "NÃO (Usou Principal)",
            "3_origem_resposta": ev.from_cache ? "Cache SQLite Local" : "API Google Gemini (Ao Vivo)",
            "4_tamanho_payload_kb": ev.payload_kb !== undefined ? ev.payload_kb + " KB" : "-",
            "5_tempo_dns_tcp_ms": ev.dns_tcp_ms !== undefined ? ev.dns_tcp_ms + " ms" : "-",
            "6_tempo_ate_http200_s": ev.http_connect_sec !== undefined ? ev.http_connect_sec + "s" : "-",
            "7_tempo_1o_pensamento_s": ev.first_thought_sec !== undefined ? ev.first_thought_sec + "s" : "-",
            "8_duracao_raciocinio_thinking_s": ev.thinking_duration_sec !== undefined ? ev.thinking_duration_sec + "s" : "-",
            "9_tempo_1o_texto_ttft_s": ev.ttft_sec + "s",
            "10_duracao_escrita_streaming_s": ev.generation_duration_sec !== undefined ? ev.generation_duration_sec + "s" : "-",
            "11_tempo_total_segundos": ev.elapsed_sec + "s",
            "12_consultas_sqlite": (ev.tools_called || []).join(", "),
            "13_historico_tentativas": (ev.attempts_log || []).join(" -> "),
          });

          await refreshWorkoutsList(currentWorkoutId, false);
        } else if (ev.type === "error") {
          console.error("❌ [GeminiCoach] Erro na geração do relatório:", ev.error);
          container.innerHTML = `<p style="color:#ef4444;">❌ Erro: ${ev.error}</p>`;
        }
      }
    }
  } catch (err) {
    console.error("❌ [GeminiCoach] Falha na conexão com o servidor:", err);
    container.innerHTML = `<p style="color:#ef4444;">❌ Falha ao contatar servidor: ${err}</p>`;
  } finally {
    btn.disabled = false;
    btnRegen.disabled = false;
  }
}

async function sendChatMessage() {
  const input = document.getElementById("chat-input");
  const question = input.value.trim();
  if (!question) return;

  const messagesBox = document.getElementById("chat-messages");
  const sendBtn = document.getElementById("btn-chat-send");

  messagesBox.innerHTML += `
    <div style="background:var(--bg-surface-nested); border:1px solid var(--border); padding:10px 14px; border-radius:var(--radius-card); align-self:flex-end; max-width:85%;">
      <strong style="color:var(--orange-primary);">Você:</strong> ${question}
    </div>
  `;
  input.value = "";
  sendBtn.disabled = true;

  const loadingId = "chat-loading-" + Date.now();
  messagesBox.innerHTML += `
    <div id="${loadingId}" style="color:#38bdf8; font-size:13px;">⏳ Consultando histórico SQLite e pensando...</div>
  `;
  messagesBox.scrollTop = messagesBox.scrollHeight;

  console.log(
    `%c💬 [GeminiCoach Chat] Enviando pergunta: "${question}"`,
    "color: #38bdf8; font-weight: bold;"
  );

  try {
    const res = await fetch("/api/chat_ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        workout_id: currentWorkoutId,
        chat_history: chatHistory,
      }),
    });
    const data = await res.json();
    document.getElementById(loadingId)?.remove();

    if (data.error) {
      console.error("❌ [GeminiCoach Chat] Erro:", data.error);
      messagesBox.innerHTML += `<div style="color:#ef4444;">❌ ${data.error}</div>`;
    } else {
      chatHistory.push({ role: "user", content: question });
      chatHistory.push({ role: "assistant", content: data.answer_md });
      const meta = data.call_metadata || {};
      const elapsedTxt = meta.elapsed_sec !== undefined ? ` em ${meta.elapsed_sec}s` : "";
      const roleTag = meta.used_fallback ? "Fallback" : "Principal";

      console.log(
        `%c✅ [GeminiCoach Chat] Respondido por: ${data.model_used} (${roleTag})${elapsedTxt}`,
        "color: #22c55e; font-weight: bold;"
      );
      console.table({
        modelo_que_respondeu: data.model_used,
        usou_fallback: meta.used_fallback ? "SIM" : "NÃO",
        tempo_total_segundos: meta.elapsed_sec,
        tools_sqlite: (data.tools_called || []).join(", ") || "Nenhuma tool extra necessária",
        historico_tentativas: (meta.attempts_log || []).join(" -> "),
      });

      const toolsText =
        data.tools_called && data.tools_called.length
          ? ` &bull; SQLite: ${data.tools_called.join(", ")}`
          : "";
      const modelNote = `
        <div class="chat-bubble-meta">
          <svg class="icon icon-sm" style="stroke:var(--orange-primary);" viewBox="0 0 24 24"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>
          <strong>${data.model_used || "Gemini"}</strong> (${roleTag}${elapsedTxt})${toolsText}
        </div>
      `;
      messagesBox.innerHTML += `
        <div class="chat-bubble-coach">
          ${modelNote}
          <div class="ai-report-box">
            ${marked.parse(data.answer_md)}
          </div>
        </div>
      `;
    }
  } catch (err) {
    document.getElementById(loadingId)?.remove();
    console.error("❌ [GeminiCoach Chat] Falha:", err);
    messagesBox.innerHTML += `<div class="chat-bubble-coach" style="color:var(--coral-primary); border-color:var(--coral-primary);">Falha ao contatar treinador: ${err}</div>`;
  } finally {
    sendBtn.disabled = false;
    messagesBox.scrollTop = messagesBox.scrollHeight;
  }
}

// Upload de .FIT (suporta 1 ou múltiplos arquivos de uma vez)
function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = (err) => reject(err);
    reader.readAsDataURL(file);
  });
}

async function previewFitFile() {
  const fileInput = document.getElementById("fit-file-input");
  const files = Array.from(fileInput.files || []);
  if (files.length === 0) return;

  const previewBox = document.getElementById("upload-preview-box");
  previewBox.style.display = "block";
  previewBox.innerHTML = `⏳ Lendo ${files.length} arquivo(s) .FIT...`;

  pendingUploadFiles = [];
  const previewLines = [];

  for (const file of files) {
    const base64 = await readFileAsBase64(file);
    const res = await fetch("/api/preview_fit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_base64: base64, file_name: file.name }),
    });
    const data = await res.json();
    if (data.ok && data.preview) {
      const p = data.preview;
      pendingUploadFiles.push({
        file_name: file.name,
        file_base64: base64,
        detected_type: p.metadata.workout_type_detected,
      });
      if (files.length === 1) {
        document.getElementById("upload-workout-type").value = p.metadata.workout_type_detected;
      }
      previewLines.push(
        `✅ <strong>${file.name}</strong> → Data do treino: <strong>${(p.metadata.date || "").replace("T", " ")}</strong> | Detectado: <strong>${p.metadata.workout_type_detected}</strong> | ${p.summary.total_distance_km} km @ ${p.summary.avg_pace_min_km}/km`
      );
    } else {
      previewLines.push(`❌ <strong>${file.name}</strong>: Erro ao ler (${data.error})`);
    }
  }

  previewBox.innerHTML = previewLines.join("<br/>");
}

async function submitFitUpload() {
  if (!pendingUploadFiles || pendingUploadFiles.length === 0) {
    alert("Selecione pelo menos um arquivo .FIT primeiro!");
    return;
  }

  const singleType = document.getElementById("upload-workout-type").value;
  const rpe_effort = document.getElementById("upload-rpe").value;
  const weather_or_notes = document.getElementById("upload-notes").value;

  let lastWorkoutId = null;
  for (const item of pendingUploadFiles) {
    const workout_type_confirmed = pendingUploadFiles.length === 1 ? singleType : item.detected_type;
    const res = await fetch("/api/upload_fit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_base64: item.file_base64,
        file_name: item.file_name,
        workout_type_confirmed,
        rpe_effort: rpe_effort ? Number(rpe_effort) : null,
        weather_or_notes,
      }),
    });
    const data = await res.json();
    if (data.ok) {
      lastWorkoutId = data.workout_id;
    } else {
      alert(`Erro ao salvar ${item.file_name}: ${data.error}`);
    }
  }

  if (lastWorkoutId) {
    pendingUploadFiles = [];
    document.getElementById("fit-file-input").value = "";
    document.getElementById("upload-preview-box").style.display = "none";
    await refreshWorkoutsList(lastWorkoutId);
    switchTab("workout");
  }
}

// Aba Evolução
async function loadEvolutionView() {
  const res = await fetch("/api/evolution");
  const data = await res.json();
  const timeline = data.chronological_timeline || [];

  const cardsBox = document.getElementById("evolution-summary-cards");
  cardsBox.innerHTML = `
    <div class="metric-card">
      <div class="metric-header">
        <span><svg class="icon" style="stroke:var(--orange-primary);" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg> Sessões Registradas</span>
        <span class="badge badge-orange">HISTÓRICO</span>
      </div>
      <div class="metric-value">${data.total_workouts || 0}</div>
      <div class="metric-sub">Corridas salvas com JSON e telemetria no SQLite</div>
    </div>
    <div class="metric-card">
      <div class="metric-header">
        <span><svg class="icon" style="stroke:var(--orange-primary);" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> Volume Acumulado</span>
        <span class="badge badge-neutral">TOTAL</span>
      </div>
      <div class="metric-value">${data.total_distance_accumulated_km || 0} <span style="font-size:14px; color:var(--text-muted); font-weight:500;">km</span></div>
      <div class="metric-sub">Distância total somada de todas as sessões</div>
    </div>
    <div class="metric-card">
      <div class="metric-header">
        <span><svg class="icon" style="stroke:var(--green-primary);" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg> Maior Distância</span>
        <span class="badge badge-good">RECORDE</span>
      </div>
      <div class="metric-value">${data.longest_workout ? data.longest_workout.distance_km + ' <span style="font-size:14px; color:var(--text-muted); font-weight:500;">km</span>' : "-"}</div>
      <div class="metric-sub">Pace médio: <strong>${data.longest_workout ? data.longest_workout.avg_pace_min_km + "/km" : "-"}</strong></div>
    </div>
    <div class="metric-card">
      <div class="metric-header">
        <span><svg class="icon" style="stroke:var(--amber-primary);" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Maior Potência Média</span>
        <span class="badge badge-warn">WATTS</span>
      </div>
      <div class="metric-value">${data.highest_power_workout ? data.highest_power_workout.avg_power_watts + ' <span style="font-size:14px; color:var(--text-muted); font-weight:500;">W</span>' : "-"}</div>
      <div class="metric-sub">Pace médio: <strong>${data.highest_power_workout ? data.highest_power_workout.avg_pace_min_km + "/km" : "-"}</strong></div>
    </div>
  `;

  const dates = timeline.map((t) => `${t.start_time_iso.slice(0, 10)} (${t.workout_type})`);
  const ef = timeline.map((t) => t.aerobic_efficiency_factor);
  const hrs = timeline.map((t) => t.avg_hr_bpm);

  Plotly.newPlot(
    "chart-evolution",
    [
      {
        x: dates,
        y: ef,
        name: "Fator de Eficiência Aeróbica (Velocidade / FC)",
        type: "scatter",
        mode: "lines+markers",
        line: { color: "#ff5500", width: 2.8 },
        marker: { color: "#ff5500", size: 6 },
      },
      {
        x: dates,
        y: hrs,
        name: "FC Média (bpm)",
        type: "bar",
        yaxis: "y2",
        opacity: 0.25,
        marker: { color: "#38bdf8" },
      },
    ],
    {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: "#94a3b8", family: "'Plus Jakarta Sans', sans-serif", size: 11 },
      margin: { l: 50, r: 50, t: 20, b: 60 },
      yaxis: { title: "Eficiência Aeróbica (Maior = Melhor)", gridcolor: "#1c1e28", zerolinecolor: "#1c1e28" },
      yaxis2: { title: "FC Média (bpm)", overlaying: "y", side: "right", showgrid: false },
    },
    { responsive: true }
  );
}

// Aba Perfil
async function loadProfile() {
  const res = await fetch("/api/profile");
  const p = await res.json();
  document.getElementById("prof-name").value = p.name || "";
  document.getElementById("prof-age").value = p.age || 25;
  document.getElementById("prof-weight").value = p.weight_kg || 75;
  document.getElementById("prof-max-hr").value = p.max_hr_bpm || 195;
  document.getElementById("prof-rest-hr").value = p.resting_hr_bpm || 60;
  document.getElementById("prof-exp").value = p.running_experience_months || 2;
  document.getElementById("prof-routine").value = p.weekly_routine_description || "";
  document.getElementById("prof-goals").value = p.current_goals || "";
}

async function saveProfile() {
  const payload = {
    name: document.getElementById("prof-name").value,
    age: Number(document.getElementById("prof-age").value),
    weight_kg: Number(document.getElementById("prof-weight").value),
    max_hr_bpm: Number(document.getElementById("prof-max-hr").value),
    resting_hr_bpm: Number(document.getElementById("prof-rest-hr").value),
    running_experience_months: Number(document.getElementById("prof-exp").value),
    weekly_routine_description: document.getElementById("prof-routine").value,
    current_goals: document.getElementById("prof-goals").value,
  };
  const res = await fetch("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data.ok) {
    const msg = document.getElementById("prof-save-msg");
    msg.textContent = "✅ Perfil atualizado com sucesso!";
    setTimeout(() => (msg.textContent = ""), 3000);
  }
}
