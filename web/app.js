// AFK Neural Clone Studio — Frontend Controller

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const statusBadge = document.getElementById("status-badge");
  const currentPhaseTag = document.getElementById("current-phase-tag");
  const progressPercent = document.getElementById("progress-percent");
  const progressCircle = document.getElementById("progress-circle");
  const valLoss = document.getElementById("val-loss");
  const valAccuracy = document.getElementById("val-accuracy");
  const valEpoch = document.getElementById("val-epoch");
  const valEta = document.getElementById("val-eta");
  
  const sampleIncoming = document.getElementById("sample-incoming");
  const samplePredicted = document.getElementById("sample-predicted");
  const sampleReal = document.getElementById("sample-real");

  const durationSlider = document.getElementById("duration-slider");
  const durationDisplay = document.getElementById("duration-display");

  const btnStart = document.getElementById("btn-start");
  const btnPause = document.getElementById("btn-pause");
  const btnStop = document.getElementById("btn-stop");

  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const logsConsole = document.getElementById("logs-console");
  const btnClearLogs = document.getElementById("btn-clear-logs");

  const lossCanvas = document.getElementById("loss-canvas");
  const ctx = lossCanvas.getContext("2d");

  const circleCircumference = 2 * Math.PI * 66; // r=66 -> ~414.69
  progressCircle.style.strokeDasharray = circleCircumference;
  progressCircle.style.strokeDashoffset = circleCircumference;

  let lossHistory = [];
  let isPolling = true;

  // Format seconds to HH:MM:SS
  function formatTime(seconds) {
    if (!seconds || seconds <= 0) return "00:00:00";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  // Update Progress Circle
  function setProgress(pct) {
    const val = Math.max(0, Math.min(100, pct));
    const offset = circleCircumference - (val / 100) * circleCircumference;
    progressCircle.style.strokeDashoffset = offset;
    progressPercent.textContent = `${Math.round(val)}%`;
  }

  // Draw Dynamic Loss Curve
  function drawLossChart() {
    const w = lossCanvas.width = lossCanvas.offsetWidth * window.devicePixelRatio;
    const h = lossCanvas.height = 130 * window.devicePixelRatio;
    ctx.clearRect(0, 0, w, h);

    if (lossHistory.length < 2) {
      ctx.fillStyle = "rgba(255,255,255,0.2)";
      ctx.font = `${12 * window.devicePixelRatio}px Inter, sans-serif`;
      ctx.fillText("Ожидание данных обучения...", 20 * window.devicePixelRatio, h / 2);
      return;
    }

    const maxLoss = Math.max(...lossHistory, 1.5);
    const minLoss = Math.min(...lossHistory, 0.0);
    const range = maxLoss - minLoss || 1.0;

    // Grid lines
    ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
    ctx.lineWidth = 1;
    for (let i = 1; i <= 3; i++) {
      const y = (h / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Path
    ctx.beginPath();
    lossHistory.forEach((val, idx) => {
      const x = (idx / (lossHistory.length - 1)) * w;
      const y = h - ((val - minLoss) / range) * (h * 0.8) - (h * 0.1);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    // Stroke
    ctx.strokeStyle = "#ec4899";
    ctx.lineWidth = 2.5 * window.devicePixelRatio;
    ctx.stroke();

    // Fill under curve
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(236, 72, 153, 0.25)");
    grad.addColorStop(1, "rgba(236, 72, 153, 0.0)");
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Sync state from server
  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      // Badges & Phase
      if (data.is_training) {
        statusBadge.textContent = "ОБУЧЕНИЕ";
        statusBadge.className = "badge badge-active";
        btnStart.disabled = true;
        btnPause.disabled = false;
        btnStop.disabled = false;
      } else if (data.is_paused) {
        statusBadge.textContent = "ПАУЗА";
        statusBadge.className = "badge badge-paused";
        btnStart.disabled = false;
        btnStart.textContent = "Продолжить";
        btnPause.disabled = true;
        btnStop.disabled = false;
      } else {
        statusBadge.textContent = "ГОТОВО / ОЖИДАНИЕ";
        statusBadge.className = "badge badge-idle";
        btnStart.disabled = false;
        btnStart.innerHTML = '<span class="btn-icon">▶</span> Запустить обучение';
        btnPause.disabled = true;
        btnStop.disabled = true;
      }

      currentPhaseTag.textContent = data.phase || "Ожидание запуска";
      setProgress(data.progress_percent || 0);

      valLoss.textContent = (data.loss || 1.45).toFixed(4);
      valAccuracy.textContent = `${(data.accuracy || 12).toFixed(1)}%`;
      valEpoch.textContent = `${data.epoch || 0} / ${data.total_epochs || 7}`;
      valEta.textContent = formatTime(data.eta_seconds);

      // Samples & RL Reward
      if (data.current_sample && data.current_sample.incoming) {
        const dateTag = data.current_sample.date ? ` [${data.current_sample.date.replace('T', ' ').slice(0, 16)}]` : '';
        sampleIncoming.textContent = `«${data.current_sample.incoming}» (${data.current_sample.source || 'result.json'}${dateTag})`;
        samplePredicted.textContent = `«${data.current_sample.predicted || '...'}»`;
        sampleReal.textContent = `«${data.current_sample.reply || '...'}»`;

        const sampleReward = document.getElementById("sample-reward");
        if (sampleReward && data.current_sample.reward_status) {
          const r = data.current_sample.reward || 0;
          let extraHints = "";
          if (data.current_sample.feedback) {
            extraHints += `<div style="margin-top: 6px; font-size: 0.82rem; opacity: 0.95;">💡 <b>Замечание:</b> ${escapeHtml(data.current_sample.feedback)}</div>`;
          }
          if (data.current_sample.suggestion) {
            extraHints += `<div style="margin-top: 4px; font-size: 0.82rem; opacity: 0.95; color: #a7f3d0;">✨ <b>Идеал:</b> «${escapeHtml(data.current_sample.suggestion)}»</div>`;
          }

          sampleReward.innerHTML = `<div>${r > 0 ? '+' : ''}${r.toFixed(2)} | ${escapeHtml(data.current_sample.reward_status)}</div>${extraHints}`;
          if (r > 0.4) {
            sampleReward.className = "reward-pill pill-reward";
          } else if (r < -0.3) {
            sampleReward.className = "reward-pill pill-penalty";
          } else {
            sampleReward.className = "reward-pill pill-neutral";
          }
        }
      }

      // Loss chart
      if (data.loss_history && data.loss_history.length > 0) {
        lossHistory = data.loss_history;
        drawLossChart();
      }

      // Logs
      if (data.recent_logs && data.recent_logs.length > 0) {
        logsConsole.innerHTML = data.recent_logs.map(l => `<div class="log-line">${escapeHtml(l)}</div>`).join("");
        logsConsole.scrollTop = logsConsole.scrollHeight;
      }

    } catch (e) {
      console.warn("Status fetch error:", e);
    }
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Duration Slider
  durationSlider.addEventListener("input", (e) => {
    const val = e.target.value;
    durationDisplay.textContent = `${val} мин.`;
  });

  // Buttons
  btnStart.addEventListener("click", async () => {
    const minutes = parseInt(durationSlider.value, 10) || 60;
    await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration_seconds: minutes * 60 })
    });
    fetchStatus();
  });

  btnPause.addEventListener("click", async () => {
    await fetch("/api/pause", { method: "POST" });
    fetchStatus();
  });

  btnStop.addEventListener("click", async () => {
    await fetch("/api/stop", { method: "POST" });
    fetchStatus();
  });

  btnClearLogs.addEventListener("click", () => {
    logsConsole.innerHTML = "";
  });

  // Interactive Chat Playground
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;

    appendMessage("user", text);
    chatInput.value = "";

    // Show typing placeholder
    const typingId = appendTypingIndicator();

    try {
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      const data = await res.json();
      removeTypingIndicator(typingId);

      if (data.type === "sticker") {
        appendMessage("ai", `[Стикер ${data.sticker_emoji}]`, data.judge);
      } else {
        appendMessage("ai", data.text || "норм", data.judge);
      }
    } catch (err) {
      removeTypingIndicator(typingId);
      appendMessage("ai", "ща сек погоди");
    }
  });

  // Quick Chips
  document.querySelectorAll(".chip-prompt").forEach(btn => {
    btn.addEventListener("click", () => {
      chatInput.value = btn.getAttribute("data-text");
      chatForm.dispatchEvent(new Event("submit"));
    });
  });

  function appendMessage(sender, text, judgeData = null) {
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-msg msg-${sender}`;

    let judgeHtml = "";
    if (judgeData && typeof judgeData === "object") {
      const score = Number(judgeData.score) || 0;
      const scoreClass = score > 0.5 ? "pill-reward" : (score < -0.3 ? "pill-penalty" : "pill-neutral");
      const sign = score > 0 ? "+" : "";
      const reason = judgeData.reason || "";
      const feedback = judgeData.feedback ? `<div class="judge-feedback">💡 <b>Контролер:</b> ${escapeHtml(judgeData.feedback)}</div>` : "";
      const suggestion = judgeData.improved_suggestion ? `<div class="judge-suggestion">✨ <b>Рекомендация:</b> «${escapeHtml(judgeData.improved_suggestion)}»</div>` : "";

      judgeHtml = `
        <div class="msg-judge-card">
          <div class="msg-judge-header">
            <span class="reward-pill ${scoreClass}">${sign}${score.toFixed(1)}</span>
            <span class="judge-reason">${escapeHtml(reason)}</span>
          </div>
          ${feedback}
          ${suggestion}
        </div>
      `;
    }

    msgDiv.innerHTML = `
      <div class="msg-author">${sender === 'user' ? 'Вы' : 'Rew (AI Clone)'}</div>
      <div class="msg-text">${escapeHtml(text)}</div>
      ${judgeHtml}
      <div class="msg-time">${timeStr}</div>
    `;
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function appendTypingIndicator() {
    const id = `typing-${Date.now()}`;
    const msgDiv = document.createElement("div");
    msgDiv.id = id;
    msgDiv.className = "chat-msg msg-ai";
    msgDiv.innerHTML = `<div class="msg-text" style="opacity: 0.6;">печатает...</div>`;
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
  }

  function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  // Polling loop
  setInterval(fetchStatus, 1500);
  fetchStatus();
  drawLossChart();
});
