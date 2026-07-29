/* Hotel AR AI Agent v3 - Full Interactive with Dedicated Module Endpoints */
(function() {
  "use strict";
  console.log("[AR Agent] Init...");

  const API = "/api";
  const uploadedFiles = [];

  // ===== Navigation =====
  function switchPanel(name) {
    console.log("[AR] -> " + name);
    document.querySelectorAll(".nav-item").forEach(function(i) { i.classList.remove("active"); });
    var nav = document.querySelector('.nav-item[data-module="' + name + '"]');
    if (nav) nav.classList.add("active");
    document.querySelectorAll(".panel").forEach(function(p) { p.classList.remove("active"); });
    var panel = document.getElementById("panel-" + name);
    if (panel) panel.classList.add("active");
  }
  window.switchPanel = switchPanel;

  document.querySelectorAll(".nav-item").forEach(function(item) {
    item.addEventListener("click", function(e) { e.preventDefault(); switchPanel(item.dataset.module); });
  });

  // ===== Helpers =====
  function setResult(elId, text) { var el = document.getElementById(elId); if (el) el.textContent = text; }
  function showLoading(elId) { setResult(elId, "处理中..."); }
  function btnDisable(el, label) { el.disabled = true; el.textContent = label || "处理中..."; }
  function btnEnable(el, label) { el.disabled = false; el.textContent = label; }

  async function uploadAndGetPath(fileInputId) {
    var input = document.getElementById(fileInputId);
    if (!input || !input.files[0]) return null;
    var fd = new FormData(); fd.append("file", input.files[0]);
    var r = await fetch(API + "/upload", { method: "POST", body: fd });
    var d = await r.json(); uploadedFiles.push(d);
    return d.path;
  }

  // ===== Direct API call helper (no AI chat) =====
  async function apiPost(endpoint, body) {
    var r = await fetch(API + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    return await r.json();
  }

  // Chat API (only for AI dialog)
  async function callChat(message) {
    var r = await fetch(API + "/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, thread_id: "web-" + Date.now() })
    });
    var d = await r.json(); return d.response || "";
  }

  // ===== OTA Step Updater =====
  function updateOtaStep(n) {
    var steps = document.querySelectorAll("#panel-ota .step");
    steps.forEach(function(s, i) {
      s.classList.remove("active", "completed");
      if (i + 1 < n) s.classList.add("completed");
      if (i + 1 === n) s.classList.add("active");
    });
  }

  // ===== File Upload (chat) =====
  async function handleUpload(e) {
    var s = document.getElementById("uploadStatus");
    var files = e.target.files;
    for (var i = 0; i < files.length; i++) {
      var f = files[i]; s.textContent = "上传中: " + f.name;
      var fd = new FormData(); fd.append("file", f);
      var r = await fetch(API + "/upload", { method: "POST", body: fd });
      var d = await r.json(); uploadedFiles.push(d);
      addMsg("system", "[已上传] " + f.name + " (" + (d.size/1024).toFixed(1) + "KB)");
    }
    s.textContent = uploadedFiles.length ? uploadedFiles.length + " 个文件" : "";
    e.target.value = "";
    uploadedFiles.length = 0;
  }
  window.handleUpload = handleUpload;

  // ===== Chat (AI 对话 专用) =====
  function sendMessage() {
    var input = document.getElementById("chatInput"), msg = input.value.trim();
    if (!msg) return; addMsg("user", msg); input.value = "";
    var filePaths = uploadedFiles.map(function(f) { return f.path; });
    streamChat(msg, filePaths);
  }
  window.sendMessage = sendMessage;

  async function streamChat(msg, filePaths) {
    addMsg("system", "思考中...", "think");
    var body = {
        message: msg,
        thread_id: "web-" + Date.now(),
        uploaded_files: filePaths || []
    };
    var r = await fetch(API + "/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });
    var reader = r.body.getReader(), dec = new TextDecoder(), full = "";
    removeThink();
    while (1) {
      var result = await reader.read(); if (result.done) break;
      var lines = dec.decode(result.value).split("\n");
      for (var li = 0; li < lines.length; li++) {
        var line = lines[li]; if (!line.startsWith("data: ")) continue;
        var d = line.slice(6); if (d === "[DONE]") break;
        try { var p = JSON.parse(d);
          if (p.type === "token") { full += p.content; updateStream(full); }
          else if (p.type === "tool_start") addMsg("system", "[工具] " + p.name);
          else if (p.type === "tool_end") addMsg("system", "[工具完成] " + p.name);
          else if (p.type === "error") addMsg("system", "[错误] " + p.content);
        } catch(ex) {}
      }
    }
    finalizeStream(full);
  }

  var sd = null;
  function removeThink() { var t = document.getElementById("think"); if (t) t.remove();
    sd = document.createElement("div"); sd.className = "msg system"; sd.id = "stream";
    sd.innerHTML = '<div class="msg-content"></div>';
    document.getElementById("chatMessages").appendChild(sd); }
  function updateStream(c) { if (sd) { sd.querySelector(".msg-content").textContent = c;
    document.getElementById("chatMessages").scrollTop = document.getElementById("chatMessages").scrollHeight; }}
  function finalizeStream(c) { if (c) updateStream(c); sd = null; }
  function addMsg(role, content, id) {
    var c = document.getElementById("chatMessages"), d = document.createElement("div");
    d.className = "msg " + role; if (id) d.id = id;
    d.innerHTML = '<div class="msg-content">' + content.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;") + "</div>";
    c.appendChild(d); c.scrollTop = c.scrollHeight;
  }

  var ci = document.getElementById("chatInput");
  if (ci) ci.addEventListener("keydown", function(e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }});

  // ===== OTA Recon (专用端点) =====
  function updateOtaPath() {
    var f = document.getElementById("otaFile").files[0];
    document.getElementById("otaPathHint").textContent = f ? f.name : "";
  }
  function updatePmsPath() {
    var f = document.getElementById("pmsFile").files[0];
    document.getElementById("pmsPathHint").textContent = f ? f.name : "";
  }
  window.updateOtaPath = updateOtaPath;
  window.updatePmsPath = updatePmsPath;

  window.runOtaRecon = async function() {
    var btn = document.querySelector("#panel-ota .btn-primary");
    btnDisable(btn, "处理中..."); updateOtaStep(1); showLoading("otaResult");
    try {
      var otaPath = await uploadAndGetPath("otaFile");
      if (!otaPath) { setResult("otaResult", "错误：请上传OTA报表"); btnEnable(btn, "开始对账"); return; }
      updateOtaStep(2); setResult("otaResult", "OTA已上传，正在上传PMS...");
      var pmsPath = await uploadAndGetPath("pmsFile");
      if (!pmsPath) { setResult("otaResult", "错误：请上传PMS报表"); btnEnable(btn, "开始对账"); return; }
      updateOtaStep(3); setResult("otaResult", "正在匹配订单...");
      var resp = await apiPost("/ota/recon", { ota_path: otaPath, pms_path: pmsPath });
      updateOtaStep(4); setResult("otaResult", "正在计算佣金...");
      updateOtaStep(5);
      setResult("otaResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
    } catch(e) { setResult("otaResult", "错误：" + e.message); }
    btnEnable(btn, "开始对账");
  };

  // ===== Aging (专用端点) =====
  window.runAging = async function() {
    var btn = document.querySelector("#panel-aging .btn-primary");
    btnDisable(btn); showLoading("agingResult");
    try {
      var path = await uploadAndGetPath("agingFile");
      if (!path) { setResult("agingResult", "错误：请上传应收台账"); btnEnable(btn, "开始分析"); return; }
      var date = document.getElementById("agingDate").value || "";
      var resp = await apiPost("/aging/analyze", { receivable_path: path, as_of_date: date });
      setResult("agingResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
      if (resp.ok) {
        // Parse amounts and update dashboard
        var ids = {"1-30":"a30","31-60":"a60","61-90":"a90","91-120":"a120","121-180":"a180","180+":"a180p"};
        for (var key in ids) {
          var re = new RegExp(key + ".*?([0-9,]+\\.?[0-9]*)", "i");
          var m = resp.result.match(re);
          if (m) document.getElementById(ids[key]).textContent = m[1];
        }
      }
    } catch(e) { setResult("agingResult", "错误：" + e.message); }
    btnEnable(btn, "开始分析");
  };

  // ===== Daily Check (专用端点) =====
  window.runDailyCheck = async function() {
    var btn = document.querySelector("#panel-daily .btn-primary");
    btnDisable(btn); showLoading("dailyResult");
    try {
      var night = await uploadAndGetPath("nightFile"), ar = await uploadAndGetPath("arLedgerFile");
      if (!night || !ar) { setResult("dailyResult", "错误：请上传两个文件"); btnEnable(btn, "开始核对"); return; }
      var resp = await apiPost("/daily/check", { night_report_path: night, ar_ledger_path: ar });
      setResult("dailyResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
    } catch(e) { setResult("dailyResult", "错误：" + e.message); }
    btnEnable(btn, "开始核对");
  };

  // ===== Daily AR (专用端点 + 文件上传) =====
  window.runDailyAr = async function(type) {
    var card = document.querySelector('#panel-ar .ar-card[onclick*="' + type + '"]');
    if (card) { card.style.opacity = "0.5"; card.style.pointerEvents = "none"; }
    showLoading("arResult");
    try {
      // 根据类型收集对应文件
      var bankAuthPath = "", pmsDepositPath = "", banquetPath = "", guestPath = "";
      if (type === "preauth") {
        bankAuthPath = await uploadAndGetPath("arBankAuthFile") || "";
        pmsDepositPath = await uploadAndGetPath("arPmsDepositFile") || "";
      } else if (type === "classify") {
        pmsDepositPath = await uploadAndGetPath("arPmsDepositFile") || "";
      } else if (type === "alert") {
        pmsDepositPath = await uploadAndGetPath("arPmsDepositFile") || "";
        guestPath = await uploadAndGetPath("arGuestLedgerFile") || "";
      } else if (type === "longstay") {
        guestPath = await uploadAndGetPath("arGuestLedgerFile") || "";
      } else if (type === "banquet") {
        banquetPath = await uploadAndGetPath("arBanquetFile") || "";
      }
      var resp = await apiPost("/daily/ar", {
        type: type,
        bank_auth_path: bankAuthPath,
        pms_deposit_path: pmsDepositPath,
        banquet_contract_path: banquetPath,
        guest_ledger_path: guestPath
      });
      setResult("arResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
    } catch(e) { setResult("arResult", "错误：" + e.message); }
    if (card) { card.style.opacity = "1"; card.style.pointerEvents = "auto"; }
  };

  // ===== Card Recon (专用端点) =====
  window.runCardRecon = async function() {
    var btn = document.querySelector("#panel-card .btn-primary");
    btnDisable(btn); showLoading("cardResult");
    try {
      var bank = await uploadAndGetPath("bankFile"), pms = await uploadAndGetPath("pmsCardFile");
      if (!bank || !pms) { setResult("cardResult", "错误：请上传两个文件"); btnEnable(btn, "开始对账"); return; }
      var resp = await apiPost("/card/recon", { bank_statement_path: bank, pms_card_path: pms });
      setResult("cardResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
    } catch(e) { setResult("cardResult", "错误：" + e.message); }
    btnEnable(btn, "开始对账");
  };

  // ===== Ctrip (专用端点) =====
  window.runCtrip = async function() {
    var btn = document.querySelector("#panel-ctrip .btn-primary");
    btnDisable(btn); showLoading("ctripResult");
    try {
      var path = await uploadAndGetPath("ctripFile");
      if (!path) { setResult("ctripResult", "错误：请上传携程结算单"); btnEnable(btn, "计算佣金"); return; }
      var resp = await apiPost("/ctrip/commission", { settlement_path: path });
      setResult("ctripResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
    } catch(e) { setResult("ctripResult", "错误：" + e.message); }
    btnEnable(btn, "计算佣金");
  };

  // ===== Config (专用端点) =====
  window.runConfig = async function(action) {
    var label = action || "unknown";
    var card = document.querySelector('#panel-config .config-card[onclick*="' + label + '"]');
    if (card) { card.style.opacity = "0.5"; card.style.pointerEvents = "none"; }
    showLoading("configResult");
    try {
      var sourcePath = "";
      if (action === "check") {
        var fi = document.getElementById("configCheckFile");
        if (fi && fi.files[0]) sourcePath = await uploadAndGetPath("configCheckFile") || "";
      }
      var resp = await apiPost("/config/" + action, { action: action, source_path: sourcePath });
      setResult("configResult", resp.ok ? resp.result : ("错误：" + (resp.detail || "未知")));
    } catch(e) { setResult("configResult", "错误：" + e.message); }
    if (card) { card.style.opacity = "1"; card.style.pointerEvents = "auto"; }
  };

  // ===== Scheduler (专用端点) =====
  window.scheduleRun = async function(mode) {
    var btn = document.querySelector('#panel-scheduler .sched-card button[onclick*="' + mode + '"]');
    if (btn) btnDisable(btn, "执行中...");
    try {
      var resp = await apiPost("/scheduler/" + mode, {});
      var resultEl = document.getElementById("schedulerResult");
      if (resultEl && resp.ok) {
        resultEl.textContent = resp.results ? resp.results.join("\n\n") : "无结果";
      } else if (resultEl) {
        resultEl.textContent = "错误：" + (resp.detail || "未知");
      }
    } catch(e) {
      var resultEl = document.getElementById("schedulerResult");
      if (resultEl) resultEl.textContent = "错误：" + e.message;
    }
    if (btn) btnEnable(btn, mode === "daily" ? "执行日清" : "执行月度");
  };

  window.viewApprovals = function() {
    addMsg("system", "[审批] 审批队列将在部署时配置");
  };

  // ===== Health =====
  async function checkHealth() {
    try { var r = await fetch(API + "/health"), d = await r.json();
      document.getElementById("statusText").textContent = d.status || "OK";
      document.getElementById("statusDot").className = "status-dot";
    } catch(e) { document.getElementById("statusText").textContent = "离线";
      document.getElementById("statusDot").className = "status-dot error"; }
  }
  checkHealth(); setInterval(checkHealth, 30000);
  console.log("[AR Agent] Ready");
})();

function uploadAndSetPath(fileInputId, hintId) {
    const fileInput = document.getElementById(fileInputId);
    const hint = document.getElementById(hintId);
    if (!fileInput || !fileInput.files.length) return;
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    fetch('/api/upload', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(d => {
            fileInput.dataset.path = d.path;
            hint.textContent = d.path;
            hint.style.color = '#22c55e';
        })
        .catch(e => { hint.textContent = 'Upload failed'; hint.style.color = '#ef4444'; });
}

function runCorpRecon() {
    const hint = document.getElementById('corpPathHint');
    const fileInput = document.getElementById('corpFile');
    const path = fileInput.dataset.path || '';
    if (!path) { alert('Please upload file first'); return; }
    const res = document.getElementById('corpResult');
    res.innerHTML = '<p>Processing...</p>';
    fetch('/api/corp/recon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receivable_path: path })
    })
    .then(r => r.json())
    .then(d => { res.innerHTML = '<pre>' + d.result + '</pre>'; })
    .catch(e => { res.innerHTML = '<p class="error">Error: ' + e + '</p>'; });
}

function runBatchOta() {
    const status = document.getElementById('batchOtaStatus');
    status.textContent = 'Running...'; status.className = 'batch-status running';
    const res = document.getElementById('batchResult');
    res.innerHTML = '<p>Running OTA batch...</p>';
    fetch('/api/batch/ota', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            status.textContent = 'Done'; status.className = 'batch-status done';
            res.innerHTML = '<pre>' + d.result + '</pre>';
        })
        .catch(e => {
            status.textContent = 'Error'; status.className = 'batch-status error';
            res.innerHTML = '<p class="error">Error: ' + e + '</p>';
        });
}

function runBatchCard() {
    const status = document.getElementById('batchCardStatus');
    status.textContent = 'Running...'; status.className = 'batch-status running';
    const res = document.getElementById('batchResult');
    res.innerHTML = '<p>Running card batch...</p>';
    fetch('/api/batch/card', { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            status.textContent = 'Done'; status.className = 'batch-status done';
            res.innerHTML = '<pre>' + d.result + '</pre>';
        })
        .catch(e => {
            status.textContent = 'Error'; status.className = 'batch-status error';
            res.innerHTML = '<p class="error">Error: ' + e + '</p>';
        });
}

function runBatchAll() {
    const status = document.getElementById('batchAllStatus');
    status.textContent = 'Running...'; status.className = 'batch-status running';
    const res = document.getElementById('batchResult');
    res.innerHTML = '<p>Running all batches...</p>';

    Promise.all([
        fetch('/api/batch/ota', { method: 'POST' }).then(r => r.json()),
        fetch('/api/batch/card', { method: 'POST' }).then(r => r.json())
    ])
    .then(([ota, card]) => {
        status.textContent = 'Done'; status.className = 'batch-status done';
        res.innerHTML = '<pre>' + ota.result + '\n\n' + card.result + '</pre>';
    })
    .catch(e => {
        status.textContent = 'Error'; status.className = 'batch-status error';
        res.innerHTML = '<p class="error">Error: ' + e + '</p>';
    });
}

function runInvoice() {
    const fileInput = document.getElementById('invoiceFile');
    const path = fileInput.dataset.path || '';
    if (!path) { alert('Please upload file first'); return; }
    const invType = document.getElementById('invoiceType').value;
    const res = document.getElementById('invoiceResult');
    res.innerHTML = '<p>Generating invoice...</p>';
    fetch('/api/invoice/gen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receivable_path: path, invoice_type: invType })
    })
    .then(r => r.json())
    .then(d => { res.innerHTML = '<pre>' + d.result + '</pre>'; })
    .catch(e => { res.innerHTML = '<p class="error">Error: ' + e + '</p>'; });
}
