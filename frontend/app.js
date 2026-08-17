/* Hotel AR AI Agent v3 - Full Interactive with Dedicated Module Endpoints */
(function() {
  "use strict";
  console.log("[AR Agent] Init...");

  const API = "/api";
  const uploadedFiles = [];

  // ===== Navigation =====
  function switchPanel(name) {
    console.log("[AR] -> " + name);
    // 更新导航高亮
    document.querySelectorAll(".nav-item").forEach(function(i) {
      i.classList.remove("active");
    });
    var nav = document.querySelector('.nav-item[data-module="' + name + '"]');
    if (nav) nav.classList.add("active");

    // 隐藏所有面板
    document.querySelectorAll(".panel").forEach(function(p) {
      p.classList.remove("active");
    });

    // 显示目标面板
    var panel = document.getElementById("panel-" + name);
    if (panel) {
      panel.classList.add("active");
      console.log("[AR] panel active:", "panel-" + name);
    } else {
      console.error("[AR] panel not found:", "panel-" + name);
    }
  }
  window.switchPanel = switchPanel;

    document.querySelectorAll(".nav-item").forEach(function(item) {
    item.addEventListener("click", function(e) {
      e.preventDefault();
      e.stopImmediatePropagation();
      switchPanel(item.dataset.module);
    });
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
  }
  window.handleUpload = handleUpload;

  // ===== Chat (AI 对话 专用) =====
  function sendMessage() {
    var input = document.getElementById("chatInput"), msg = input.value.trim();
    if (!msg) return; addMsg("user", msg); input.value = "";
    var filePaths = uploadedFiles.map(function(f) { return f.path; });
    streamChat(msg, filePaths);
    uploadedFiles.length = 0;
    document.getElementById("uploadStatus").textContent = "";
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
      var ctripPath = await uploadAndGetPath("ctripFile");
      if (!ctripPath) { setResult("ctripResult", "错误：请上传携程结算单"); btnEnable(btn, "计算佣金"); return; }
      var pmsPath = await uploadAndGetPath("ctripPmsFile");
      if (!pmsPath) { setResult("ctripResult", "错误：请上传PMS营业数据"); btnEnable(btn, "计算佣金"); return; }
      var resp = await apiPost("/ctrip/commission", { settlement_path: ctripPath, pms_path: pmsPath });
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

    // ===== Scheduler (智能调度) =====
    window.scheduleRun = async function(mode) {
      var btn = document.querySelector('#panel-scheduler .sched-card button[onclick*="' + mode + '"]');
      if (btn) btnDisable(btn, "执行中...");

      var resultEl = document.getElementById("schedulerResult");
      resultEl.innerHTML = '<div class="sched-loading">正在智能调度，自动发现任务并执行...</div>';

      try {
        var resp = await apiPost("/scheduler/" + mode, {});

        if (resp.ok && resp.results) {
          var html = '<div class="sched-summary">';
          html += '<div class="sched-stat">总任务: ' + (resp.summary?.total || 0) + '</div>';
          html += '<div class="sched-stat success">成功: ' + (resp.summary?.success || 0) + '</div>';
          html += '<div class="sched-stat error">失败: ' + (resp.summary?.failed || 0) + '</div>';
          html += '</div>';

          html += '<div class="sched-timeline">';
          for (var i = 0; i < resp.results.length; i++) {
            var r = resp.results[i];
            var isErr = r.indexOf("❌") !== -1;
            html += '<div class="sched-item ' + (isErr ? 'error' : 'success') + '">';
            html += '<div class="sched-text">' + r.replace(/</g,"&lt;").replace(/>/g,"&gt;") + '</div>';
            html += '</div>';
          }
          html += '</div>';
          resultEl.innerHTML = html;
        } else {
          resultEl.textContent = "错误：" + (resp.detail || "未知");
        }
      } catch(e) {
        resultEl.textContent = "错误：" + e.message;
      }

      if (btn) btnEnable(btn, mode === "daily" ? "执行日清" : "执行月度");
    };

  window.viewApprovals = function() {
    addMsg("system", "[审批] 审批队列将在部署时配置");
  };

  // ===== Drag & Drop Upload with Validation =====
  (function initDropZone() {
    var dz = document.getElementById("dropZone");
    var fi = document.getElementById("dropFileInput");
    if (!dz) return;

    dz.addEventListener("dragover", function(e) {
      e.preventDefault();
      dz.classList.add("dragover");
    });
    dz.addEventListener("dragleave", function(e) {
      e.preventDefault();
      dz.classList.remove("dragover");
    });
    dz.addEventListener("drop", function(e) {
      e.preventDefault();
      dz.classList.remove("dragover");
      var files = e.dataTransfer.files;
      if (files.length) processDropFiles(files);
    });
  })();

  window.handleDropUpload = function(e) {
    if (e.target.files.length) processDropFiles(e.target.files);
    e.target.value = "";
  };

  async function processDropFiles(files) {
    var area = document.getElementById("uploadPreviewArea");
    var container = document.getElementById("uploadResults");
    area.style.display = "block";

    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var cardId = "ur-" + Date.now() + "-" + i;
      var card = createResultCard(cardId, f.name, "自动检测中...", "pending");
      container.appendChild(card);

      var fd = new FormData();
      fd.append("file", f);

      try {
        var r = await fetch(API + "/files/validate", {
          method: "POST",
          body: fd
        });
        var d = await r.json();
        updateResultCard(cardId, d);
      } catch (err) {
        updateResultCard(cardId, { valid: false, error: "网络错误: " + err.message });
      }
    }
  }

  function createResultCard(id, name, meta, status) {
    var div = document.createElement("div");
    div.id = id;
    div.className = "upload-result-card " + status;
    div.innerHTML =
      '<div class="ur-icon">📄</div>' +
      '<div class="ur-body">' +
        '<div class="ur-name">' + name + '</div>' +
        '<div class="ur-meta">' + meta + '</div>' +
        '<div class="ur-detail"></div>' +
      '</div>';
    return div;
  }

  function updateResultCard(id, d) {
    var card = document.getElementById(id);
    if (!card) return;
    var body = card.querySelector(".ur-body");

    if (d.valid) {
      card.className = "upload-result-card success";
      var preview = "";
      if (d.preview) {
        preview = "工作表: " + (d.preview.sheet || "-") +
                  " | 列数: " + d.preview.cols +
                  " | 行数: " + d.preview.rows +
                  "\n表头: " + (d.preview.headers || []).join(", ");
      }
      body.innerHTML =
        '<div class="ur-name">' + d.filename + '</div>' +
        '<div class="ur-meta">' + (d.file_kind || "未知类型") +
        ' | ' + (d.size / 1024).toFixed(1) + ' KB</div>' +
        '<div class="ur-preview">' + preview + '</div>' +
        '<div class="ur-actions">' +
          '<a class="btn-xs" href="' + (d.download_url || ("/api/download?path=" + encodeURIComponent(d.path))) + '" download>下载</a>' +
          '<button class="btn-xs btn-danger" onclick="deleteFile(\'' + d.path.replace(/\\/g, "\\\\") + '\', \'uploads\')">删除</button>' +
        '</div>';
    } else {
      card.className = "upload-result-card error";
      body.innerHTML =
        '<div class="ur-name">' + (d.filename || "未知文件") + '</div>' +
        '<div class="ur-error">❌ ' + (d.error || "校验失败") + '</div>' +
        '<div class="ur-actions">' +
          '<button class="btn-xs btn-danger" onclick="deleteFile(\'' + (d.path || "").replace(/\\/g, "\\\\") + '\', \'uploads\')">删除</button>' +
        '</div>';
    }
  }
    // ===== File Manager =====
  window._fileMgrState = window._fileMgrState || {};

  window.loadFileList = async function(dirType, subPath) {
    subPath = subPath || "";
    window._fileMgrState[dirType] = subPath;
    var elId = dirType + "List";
    var el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = '<div class="filemgr-loading">加载中...</div>';
    try {
      var url = API + "/files?dir_type=" + dirType;
      if (subPath) url += "&sub_path=" + encodeURIComponent(subPath);
      var r = await fetch(url);
      var d = await r.json();

      // 面包屑
      var breadcrumb = '';
      if (subPath) {
        breadcrumb = '<div class="filemgr-breadcrumb">' +
          '<a href="#" onclick="loadFileList(\'' + dirType + '\', \'\');return false">根目录</a>';
        var parts = subPath.split('/');
        var cumul = '';
        for (var p = 0; p < parts.length; p++) {
          cumul += (cumul ? '/' : '') + parts[p];
          breadcrumb += ' / <a href="#" onclick="loadFileList(\'' + dirType + '\', \'' + cumul + '\');return false">' + parts[p] + '</a>';
        }
        breadcrumb += '</div>';
      }

      if (!d.ok || !d.files.length) {
        el.innerHTML = breadcrumb + '<div class="filemgr-empty">暂无文件</div>';
        return;
      }

      var html = breadcrumb + '<table class="filemgr-table"><thead><tr>' +
        '<th>文件名</th><th>大小</th><th>修改时间</th><th>操作</th>' +
        '</tr></thead><tbody>';
      for (var i = 0; i < d.files.length; i++) {
        var f = d.files[i];
        if (f.is_dir) {
          html += '<tr>' +
            '<td class="fname">📁 ' + f.name + '</td>' +
            '<td>-</td>' +
            '<td>' + f.mtime + '</td>' +
            '<td class="fops">' +
            '<button class="btn-xs btn-primary" onclick="loadFileList(\'' + dirType + '\', \'' + (subPath ? subPath + '/' : '') + f.name + '\')">进入</button>' +
            '<button class="btn-xs btn-danger" onclick="deleteFile(\'' + f.path.replace(/\\/g, "\\\\") + '\', \'' + dirType + '\')">删除</button>' +
            '</td></tr>';
        } else {
          var size = f.size < 1024 ? f.size + " B" :
                     f.size < 1048576 ? (f.size / 1024).toFixed(1) + " KB" :
                     (f.size / 1048576).toFixed(1) + " MB";
          html += '<tr>' +
            '<td class="fname" title="' + f.path + '">' + f.name + '</td>' +
            '<td>' + size + '</td>' +
            '<td>' + f.mtime + '</td>' +
            '<td class="fops">' +
            '<a class="btn-xs" href="' + f.download_url + '" download>下载</a>' +
            '<button class="btn-xs btn-danger" onclick="deleteFile(\'' + f.path.replace(/\\/g, "\\\\") + '\', \'' + dirType + '\')">删除</button>' +
            '</td></tr>';
        }
      }
      html += '</tbody></table>';
      el.innerHTML = html;
    } catch(e) {
      el.innerHTML = '<div class="filemgr-empty">加载失败: ' + e.message + '</div>';
    }
  };

  window.deleteFile = async function(filePath, dirType) {
    if (!confirm("确定删除该文件？")) return;
    try {
      var r = await fetch(API + "/files/delete", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: filePath})
      });
      var d = await r.json();
      if (d.ok) {
        loadFileList(dirType);
      } else {
        alert("删除失败: " + (d.detail || "未知"));
      }
    } catch(e) {
      alert("删除失败: " + e.message);
    }
  };

  window.cleanupDir = async function(dirType) {
    if (!confirm("确定清空 " + dirType + " 目录下的所有文件？此操作不可恢复！")) return;
    try {
      var subPath = window._fileMgrState[dirType] || "";
      var body = {dir_type: dirType};
      if (subPath) body.sub_path = subPath;
      var r = await fetch(API + "/files/cleanup", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      var d = await r.json();
      if (d.ok) {
        loadFileList(dirType, subPath);
      } else {
        alert("清理失败: " + (d.detail || "未知"));
      }
    } catch(e) {
      alert("清理失败: " + e.message);
    }
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