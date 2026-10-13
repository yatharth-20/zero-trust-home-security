/* ZeroTrust Home · Guardian Dashboard Application Logic */
(function() {
  'use strict';

  const $ = id => document.getElementById(id);
  const state = {
    door: false,
    pir: false,
    away: false,
    activeZone: 'entry',
    history: [],
    evalRunning: false,
    currentCamName: 'Entrance Cam'
  };

  const ZONES = {
    entry: { label: 'Entry / Porch', access: 'open' },
    living_room: { label: 'Living Room', access: 'open' },
    kitchen: { label: 'Kitchen', access: 'open' },
    study: { label: 'Study', access: 'restricted' },
    bedroom: { label: 'Bedroom', access: 'restricted' }
  };

  // -------------------- Clock & Helpers --------------------
  function updateClock() {
    const now = new Date();
    $('clock').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  setInterval(updateClock, 1000);
  updateClock();

  function showToast(msg) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.remove('hidden');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.add('hidden'), 3500);
  }

  async function api(path, method = 'GET', data = null) {
    try {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (data) opts.body = JSON.stringify(data);
      const res = await fetch(path, opts);
      return await res.json();
    } catch (err) {
      console.error('API Error:', path, err);
      return null;
    }
  }

  // -------------------- Floor Plan Build --------------------
  function buildFloorPlan() {
    const plan = $('plan');
    plan.innerHTML = '';
    for (const [key, z] of Object.entries(ZONES)) {
      const div = document.createElement('div');
      div.className = `tile ${z.access === 'restricted' ? 'restricted' : ''}`;
      div.dataset.zone = key;
      div.innerHTML = `
        <div class="zl">
          <span>${z.label}</span>
          ${z.access === 'restricted' ? '<span class="lock">RESTRICTED</span>' : ''}
          <span class="cam hidden">CAM</span>
        </div>
        <div class="chips-in" id="zone_persons_${key}"></div>
      `;
      div.addEventListener('click', () => {
        api('/api/zone', 'POST', { zone: key });
        showToast(`Camera switched to ${z.label}`);
      });
      plan.appendChild(div);
    }
  }

  // -------------------- Scenario Chips --------------------
  async function loadScenarios() {
    const data = await api('/api/scenarios');
    if (!data) return;
    $('demoCard').classList.remove('hidden');

    const renderPool = (targetId, items, isThreat) => {
      const wrap = $(targetId);
      wrap.innerHTML = '';
      for (const item of items) {
        const btn = document.createElement('button');
        btn.className = `chip ${isThreat ? 'bad' : 'ok'}`;
        btn.textContent = item.title;
        btn.title = item.description;
        btn.addEventListener('click', async () => {
          document.querySelectorAll('.chip').forEach(c => c.classList.remove('playing'));
          btn.classList.add('playing');
          const res = await api('/api/scenario', 'POST', { key: item.key });
          if (res && res.ok) {
            showToast(`Playing scenario: ${item.title}`);
          }
        });
        wrap.appendChild(btn);
      }
    };

    renderPool('benignBtns', data.benign || [], false);
    renderPool('threatBtns', data.threat || [], true);
  }

  // -------------------- Event Handlers --------------------
  function setupActions() {
    // Adults away toggle
    $('awayBtn').addEventListener('click', async () => {
      const next = !state.away;
      await api('/api/adults_away', 'POST', { away: next });
      state.away = next;
      $('awayBtn').classList.toggle('on', next);
      showToast(next ? 'Guardians marked AWAY (Child-Alone Protocol Armed)' : 'Guardians marked HOME');
    });

    // Silence alarm
    $('silenceBtn').addEventListener('click', async () => {
      await api('/api/silence', 'POST');
      showToast('Alarm silenced');
    });

    // Door sensor
    $('sDoor').addEventListener('click', async () => {
      const next = !state.door;
      await api('/api/sensors', 'POST', { door: next });
      state.door = next;
    });

    // PIR motion
    $('sPir').addEventListener('click', async () => {
      await api('/api/sensors', 'POST', { pir: true });
      showToast('PIR motion triggered');
    });

    // Acoustic Anomaly triggers (Limitation #6 Fix)
    const triggerAudio = async () => {
      const res = await api('/api/audio_anomaly', 'POST', { event: 'Glass shatter / child scream' });
      if (res && res.ok) {
        showToast('💥 Simulated Acoustic Distress / Glass Break in blind spot!');
      }
    };
    $('sAudio').addEventListener('click', triggerAudio);
    $('audioTriggerBtn').addEventListener('click', triggerAudio);

    // Camera switcher (Limitation #1 Fix)
    $('camSwitchBtn').addEventListener('click', async () => {
      const res = await api('/api/camera_switch', 'POST');
      if (res && res.ok && res.camera) {
        state.currentCamName = res.camera.name || res.camera.id;
        $('camActiveTxt').textContent = state.currentCamName;
        showToast(`Switched Camera View: ${state.currentCamName}`);
      }
    });

    // Run evaluation
    $('runEval').addEventListener('click', async () => {
      if (state.evalRunning) return;
      state.evalRunning = true;
      $('runEval').disabled = true;
      $('runEval').textContent = 'Simulating 400 scenarios...';
      const res = await api('/api/evaluate', 'POST', { n: 400, seed: 11 });
      state.evalRunning = false;
      $('runEval').disabled = false;
      $('runEval').textContent = 'Run evaluation';
      if (res) renderEvalResults(res);
    });

    // Modal close
    $('modalClose').addEventListener('click', () => $('modal').classList.add('hidden'));
  }

  // -------------------- Render Main State --------------------
  function render(s) {
    if (!s) return;

    // Mode Pill
    $('modePill').textContent = (s.mode || 'demo').toUpperCase();

    // Alarm Pill
    $('alarmPill').classList.toggle('hidden', !s.alarm_active);

    // Offline Queue Indicator (Limitation #4 Fix)
    const offlineCount = s.offline_queue_count || 0;
    const offPill = $('offlinePill');
    if (offlineCount > 0) {
      offPill.textContent = `⚠️ Offline (${offlineCount} queued)`;
      offPill.style.background = 'rgba(251,191,36,0.18)';
      offPill.style.borderColor = 'rgba(251,191,36,0.5)';
      offPill.style.color = 'var(--medium)';
    } else {
      offPill.textContent = '🌐 Online (0 queued)';
      offPill.style.background = 'rgba(52,211,153,0.12)';
      offPill.style.borderColor = 'rgba(52,211,153,0.3)';
      offPill.style.color = 'var(--low)';
    }
    if ($('stOffline')) $('stOffline').textContent = offlineCount;

    // Lighting Pill (Limitation #2 Fix)
    const lux = s.lighting_lux != null ? s.lighting_lux : 100;
    const lightPill = $('lightingPill');
    if (lux < 65) {
      lightPill.textContent = '🌙 Low-Light: CLAHE Active';
      lightPill.style.background = 'rgba(167,139,250,0.18)';
      lightPill.style.borderColor = 'rgba(167,139,250,0.5)';
      lightPill.style.color = 'var(--accent2)';
    } else {
      lightPill.textContent = '🔆 Lighting: Optimal';
      lightPill.style.background = 'rgba(110,231,249,0.1)';
      lightPill.style.borderColor = 'rgba(110,231,249,0.28)';
      lightPill.style.color = 'var(--accent)';
    }

    // Adults Away
    state.away = Boolean(s.adults_away);
    $('awayBtn').classList.toggle('on', state.away);

    // Scenario Name
    $('scenarioName').textContent = s.scenario ? `Scenario: ${s.scenario}` : '';

    // Sensors
    const sens = s.sensors || {};
    state.door = Boolean(sens.door_open);
    $('sDoor').classList.toggle('on', state.door);
    $('sDoorTxt').textContent = state.door ? 'OPEN' : 'closed';

    state.pir = Boolean(sens.pir_motion);
    $('sPir').classList.toggle('on', state.pir);
    $('sPirTxt').textContent = state.pir ? 'MOTION' : 'idle';

    // Acoustic Sensor
    const audioSpike = Boolean(sens.acoustic_anomaly);
    $('sAudio').classList.toggle('on', audioSpike);
    $('sAudioTxt').textContent = audioSpike ? 'SPIKE DETECTED' : 'listening';

    // Camera Active Zone & Name
    state.activeZone = s.zone || 'entry';
    document.querySelectorAll('.tile').forEach(t => {
      const isAct = t.dataset.zone === state.activeZone;
      t.classList.toggle('active', isAct);
      const camTag = t.querySelector('.cam');
      if (camTag) camTag.classList.toggle('hidden', !isAct);
    });

    // Assessment
    const a = s.assessment || { score: 0, level: 'LOW', signals: [], trust: {}, summary: 'Waiting for activity...', action: '' };

    // Gauge Card
    $('riskCard').dataset.level = a.level;
    $('levelBadge').textContent = a.level;
    $('score').textContent = Math.round(a.score);
    const arcLen = (Math.min(100, a.score) / 100) * 283;
    $('gArc').setAttribute('stroke-dasharray', `${arcLen} 283`);
    $('summary').textContent = a.summary || 'Normal activity';
    $('action').textContent = a.action || '';

    // Trust Ring
    const tVal = Math.round(a.trust?.overall ?? 100);
    $('trustVal').textContent = tVal;
    const rLen = (tVal / 100) * 327;
    $('rArc').setAttribute('stroke-dasharray', `${rLen} 327`);

    // Trust Bars
    const barsWrap = $('trustBars');
    barsWrap.innerHTML = '';
    const comps = ['identity', 'liveness', 'schedule', 'location', 'behavior'];
    for (const c of comps) {
      const val = Math.round(a.trust?.[c] ?? 100);
      const col = val >= 70 ? 'var(--low)' : val >= 40 ? 'var(--medium)' : 'var(--high)';
      barsWrap.innerHTML += `
        <div class="bar-row">
          <label>${c}</label>
          <div class="bar"><i style="width:${val}%; background:${col};"></i></div>
          <b>${val}%</b>
        </div>
      `;
    }

    // Why This Score (Signals)
    const sigList = $('signals');
    sigList.innerHTML = '';
    const sigs = a.signals || [];
    if (sigs.length === 0) {
      sigList.innerHTML = '<li class="empty">No risk signals — routine domestic activity.</li>';
    } else {
      for (const sig of sigs) {
        const isNeg = sig.points < 0;
        sigList.innerHTML += `
          <li class="sig ${isNeg ? 'neg' : ''}">
            <div class="t">
              <span>${sig.name.replace(/_/g, ' ').toUpperCase()}</span>
              <b>${sig.points > 0 ? '+' : ''}${sig.points} pts</b>
            </div>
            <p>${sig.reason}</p>
          </li>
        `;
      }
    }

    // Person chips in floor plan
    for (const z of Object.keys(ZONES)) {
      const container = $(`zone_persons_${z}`);
      if (container) container.innerHTML = '';
    }
    const persons = a.persons || [];
    for (const p of persons) {
      const container = $(`zone_persons_${p.zone || state.activeZone}`);
      if (container) {
        const cls = p.known ? 'ok' : 'bad';
        const init = (p.identity || 'U')[0].toUpperCase();
        container.innerHTML += `
          <div class="person ${cls}">
            <div class="av">${init}</div>
            <span>${p.identity || 'Unrecognised'}</span>
            <small>${p.role || ''}</small>
          </div>
        `;
      }
    }

    // Render Detected Faces in Camera View HUD
    const faceList = $('faceList');
    if (faceList) {
      faceList.innerHTML = '';
      if ($('faceCountTxt')) $('faceCountTxt').textContent = `${persons.length} person${persons.length === 1 ? '' : 's'} in view`;
      if ($('camLabel')) $('camLabel').textContent = `CAM-01 [${(s.zone || 'entry').toUpperCase()}]`;

      // Ensure camera video stream is active
      const streamImg = $('stream');
      if (streamImg && !streamImg.getAttribute('data-connected')) {
        streamImg.src = '/api/stream';
        streamImg.setAttribute('data-connected', 'true');
        streamImg.onerror = () => {
          setTimeout(() => { streamImg.src = '/api/stream?t=' + Date.now(); }, 2000);
        };
      }

      if (persons.length === 0) {
        faceList.innerHTML = '<p class="muted small" style="padding:4px 0;">No persons currently in camera field of view.</p>';
      } else {
        for (const p of persons) {
          const isKnown = Boolean(p.known);
          const isSpoof = (p.liveness ?? 1.0) < 0.5;
          const cardType = isSpoof ? 'spoof' : isKnown ? (p.role === 'worker' ? 'worker' : 'verified') : 'stranger';
          const init = (p.identity || 'U')[0].toUpperCase();
          const matchPct = Math.round((p.match_score || 0) * 100);
          const livePct = Math.round((p.liveness ?? 1.0) * 100);
          const badgeText = isSpoof ? '⚠️ SPOOF WARNING' : isKnown ? '✓ VERIFIED' : '⚠ UNRECOGNISED';
          const badgeColor = isSpoof ? '#d946ef' : isKnown ? 'var(--low)' : 'var(--high)';

          faceList.innerHTML += `
            <div class="face-card ${cardType}">
              <div class="face-avatar">${init}</div>
              <div class="face-info">
                <div class="face-name">
                  <span>${p.identity || `Unknown Subject #${p.track_id}`}</span>
                  <small style="color:${badgeColor}; font-weight:700;">${badgeText}</small>
                </div>
                <div class="face-sub">
                  <span>Match: <b>${isKnown ? matchPct + '%' : 'Unmatched'}</b></span>
                  <span>•</span>
                  <span>Liveness: <b>${livePct}%</b></span>
                  <span>•</span>
                  <span>Zone: <b>${(p.zone || state.activeZone).replace('_', ' ')}</b></span>
                </div>
                <div class="face-bar">
                  <i style="width:${Math.max(matchPct, 25)}%; background:${badgeColor};"></i>
                </div>
              </div>
            </div>
          `;
        }
      }
    }

    // Sparkline Timeline
    state.history.push(a.score);
    if (state.history.length > 30) state.history.shift();
    drawSparkline(state.history);

    // Stats
    const stats = s.stats || {};
    $('stAlerts').textContent = stats.alerts || 0;
    $('stSupp').textContent = stats.suppressed || 0;
    $('stEvents').textContent = stats.events || 0;

    // Outbox messages
    const outbox = $('outbox');
    outbox.innerHTML = '';
    const msgs = s.sms_outbox || [];
    if (msgs.length === 0) {
      outbox.innerHTML = '<li class="empty">No notifications sent yet.</li>';
    } else {
      for (const m of msgs.slice(-4).reverse()) {
        outbox.innerHTML += `<li><b>${m.to}</b> [${m.status}]: ${m.body}</li>`;
      }
    }

    // Guardian Override
    renderGuardianOverride(s.pending, s.events);
  }

  // -------------------- Guardian Override Card --------------------
  function renderGuardianOverride(pending, events) {
    const wrap = $('guardianBody');
    if (!pending || pending.length === 0) {
      wrap.innerHTML = `
        <div class="allclear">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="m9 12 2 2 4-4"/>
          </svg>
          <p>No high-risk security threats currently pending guardian review.</p>
        </div>
      `;
      $('incBadge').textContent = 'All clear';
      return;
    }

    const ev = pending[0];
    $('incBadge').textContent = `Incident #${ev.id}`;
    wrap.innerHTML = `
      <div class="g-event ${ev.level === 'MEDIUM' ? 'm' : ''}">
        <div class="g-score">
          <b>${Math.round(ev.score)}</b>
          <span>/ 100 — ${ev.level} RISK EVENT</span>
        </div>
        <p class="g-title">${ev.summary}</p>
        ${ev.snapshot ? `<img class="g-img" src="/evidence/${ev.snapshot}" alt="Evidence">` : ''}
        <div class="g-actions">
          <button class="g-allow" id="btnAllow">✓ ALLOW (Mark Benign)</button>
          <button class="g-deny" id="btnDeny">⚠ DENY (Confirm Threat)</button>
        </div>
        <p class="g-note">ALLOW learns harmless household behavior; DENY sounds emergency alarms.</p>
      </div>
    `;

    $('btnAllow').addEventListener('click', async () => {
      await api('/api/override', 'POST', { event_id: ev.id, decision: 'allow' });
      showToast('Incident marked ALLOWED — behavior baseline updated');
    });
    $('btnDeny').addEventListener('click', async () => {
      await api('/api/override', 'POST', { event_id: ev.id, decision: 'deny' });
      showToast('Incident CONFIRMED — emergency siren sounding!');
    });
  }

  // -------------------- Sparkline --------------------
  function drawSparkline(pts) {
    const svg = $('spark');
    if (pts.length < 2) return;
    const w = 300, h = 70;
    const step = w / (pts.length - 1);
    let d = '';
    pts.forEach((v, i) => {
      const x = i * step;
      const y = h - (Math.min(100, Math.max(0, v)) / 100) * (h - 10) - 5;
      d += (i === 0 ? `M ${x} ${y}` : ` L ${x} ${y}`);
    });
    svg.innerHTML = `
      <path d="${d}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round"/>
      <path d="${d} L 300 70 L 0 70 Z" fill="url(#grad)" opacity="0.25"/>
      <defs>
        <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--accent)"/>
          <stop offset="100%" stop-color="transparent"/>
        </linearGradient>
      </defs>
    `;
  }

  // -------------------- Research Results Table --------------------
  function renderEvalResults(res) {
    const body = $('resBody');
    if (!res || !res.systems) return;
    const sA = res.systems['A: face-recognition only'];
    const sB = res.systems['B: context-aware fusion'];
    body.innerHTML = `
      <div class="chart">
        <h3>Benchmark Metrics (${res.n_scenarios} Scenarios)</h3>
        <div class="mrow">
          <span>Precision</span>
          <div class="mbars">
            <div class="mb A"><div class="bar"><i style="width:${(sA.precision*100).toFixed(0)}%"></i></div><b>${(sA.precision*100).toFixed(1)}%</b></div>
            <div class="mb B"><div class="bar"><i style="width:${(sB.precision*100).toFixed(0)}%"></i></div><b>${(sB.precision*100).toFixed(1)}%</b></div>
          </div>
        </div>
        <div class="mrow">
          <span>Recall</span>
          <div class="mbars">
            <div class="mb A"><div class="bar"><i style="width:${(sA.recall*100).toFixed(0)}%"></i></div><b>${(sA.recall*100).toFixed(1)}%</b></div>
            <div class="mb B"><div class="bar"><i style="width:${(sB.recall*100).toFixed(0)}%"></i></div><b>${(sB.recall*100).toFixed(1)}%</b></div>
          </div>
        </div>
        <div class="mrow far">
          <span>False Alarm Rate</span>
          <div class="mbars">
            <div class="mb A"><div class="bar"><i style="width:${(sA.false_alarm_rate*100).toFixed(0)}%"></i></div><b>${(sA.false_alarm_rate*100).toFixed(1)}%</b></div>
            <div class="mb B"><div class="bar"><i style="width:${(sB.false_alarm_rate*100).toFixed(0)}%"></i></div><b>${(sB.false_alarm_rate*100).toFixed(1)}%</b></div>
          </div>
        </div>
        <div class="legend">
          <span><i style="background:#64748b"></i> System A (Face Only)</span>
          <span><i style="background:#22d3ee"></i> System B (Our Zero-Trust Fusion)</span>
        </div>
      </div>
      <div>
        <h3>Key Findings</h3>
        <ul class="note">
          <li><b>Context-Aware Accuracy:</b> System B achieves <b>${(sB.f1*100).toFixed(1)}% F1</b> compared to only ${(sA.f1*100).toFixed(1)}% for standard facial recognition.</li>
          <li><b>Massive False-Alarm Reduction:</b> False alarms drop from <b>${(sA.false_alarm_rate*100).toFixed(1)}% down to ${(sB.false_alarm_rate*100).toFixed(1)}%</b>.</li>
          <li><b>Cooldown Incident Compression:</b> Cooldown grouping eliminated <b>${(res.cooldown.reduction*100).toFixed(0)}%</b> of duplicate alert spam.</li>
        </ul>
      </div>
    `;
  }

  // -------------------- Polling Loop --------------------
  async function poll() {
    const data = await api('/api/state');
    if (data) render(data);
  }

  // -------------------- Initialization --------------------
  function init() {
    buildFloorPlan();
    loadScenarios();
    setupActions();
    setInterval(poll, 600);
    poll();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
