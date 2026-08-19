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
  var _chatThreadId = localStorage.getItem("ar_chat_thread_id") || null;
  async function callChat(message) {
    if (!_chatThreadId) {
      _chatThreadId = "web-" + Date.now();
      localStorage.setItem("ar_chat_thread_id", _chatThreadId);
    }
    var r = await fetch(API + "/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, thread_id: _chatThreadId })
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

  function newChat() {
    localStorage.removeItem("ar_chat_thread_id");
    _chatThreadId = null;
    document.getElementById("chatMessages").innerHTML =
      '<div class="msg system"><div class="msg-content">欢迎使用酒店应收会计AI智能体系统。我可以帮您：OTA对账 / 账龄分析 / 携程佣金 / 信用卡对账 / 协议客户对账 / 发票管理 / 环境验证。请直接输入需求或上传文件后开始。</div></div>';
  }
  window.newChat = newChat;

  async function streamChat(msg, filePaths) {
    addMsg("system", "思考中...", "think");
    if (!_chatThreadId) {
      _chatThreadId = "web-" + Date.now();
      localStorage.setItem("ar_chat_thread_id", _chatThreadId);
    }
    var body = {
        message: msg,
        thread_id: _chatThreadId,
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
          else if (p.type === "approval_needed") {
            // 阻断低置信度结果：清空流式显示区域，替换为审批提示
            if (sd) {
              sd.querySelector(".msg-content").textContent = (
                "⚠️ 该任务结果置信度较低（" + Math.round(p.confidence * 100) + "%），已提交人工复核，结果暂不展示。\n\n" +
                "审批ID: " + p.approval_id + "\n" +
                "任务: " + (p.task_name || "未知") + "\n\n" +
                "请前往「智能调度」→「查看审批」进行复核。\n" +
                "复核通过后，结果将正式生效。"
              );
              sd = null;
            }
          }
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

  // ===== OTA Recon (分步流水线) =====
  window._otaState = { otaPath: "", pmsPath: "", channel: "", matchData: null };

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

  function updateOtaStep(n) {
    var steps = document.querySelectorAll("#otaSteps .step");
    steps.forEach(function(s, i) {
      s.classList.remove("active", "completed");
      if (i + 1 < n) s.classList.add("completed");
      if (i + 1 === n) s.classList.add("active");
    });
  }

  function showOtaStep(stepNum) {
    for (var i = 1; i <= 5; i++) {
      var el = document.getElementById("otaStep" + i);
      if (el) el.style.display = (i === stepNum) ? "block" : "none";
    }
    updateOtaStep(stepNum);
  }

  // Step 1: 上传文件并预览
  window.runOtaUpload = async function() {
    var btn = document.getElementById("otaUploadBtn");
    btnDisable(btn, "上传中...");
    try {
      var otaPath = await uploadAndGetPath("otaFile");
      if (!otaPath) { setResult("otaResult", "错误：请上传OTA报表"); btnEnable(btn, "上传并预览"); return; }
      var pmsPath = await uploadAndGetPath("pmsFile");
      if (!pmsPath) { setResult("otaResult", "错误：请上传PMS报表"); btnEnable(btn, "上传并预览"); return; }

      window._otaState.otaPath = otaPath;
      window._otaState.pmsPath = pmsPath;

      var resp = await apiPost("/ota/upload_preview", { ota_path: otaPath, pms_path: pmsPath });
      if (!resp.ok) { setResult("otaResult", "预览失败：" + (resp.detail || "未知")); btnEnable(btn, "上传并预览"); return; }

      renderOtaPreview(resp.preview);
      showOtaStep(2);
    } catch(e) { setResult("otaResult", "错误：" + e.message); }
    btnEnable(btn, "上传并预览");
  };

  function renderOtaPreview(preview) {
    var otaHtml = "", pmsHtml = "";
    if (preview.ota) {
      otaHtml = '<div class="preview-card-inner">' +
        '<div class="preview-title">OTA报表</div>' +
        '<div class="preview-meta">文件名: ' + preview.ota.filename + '</div>' +
        '<div class="preview-meta">工作表: ' + preview.ota.sheet + '</div>' +
        '<div class="preview-meta">数据行: ' + preview.ota.rows + ' 行</div>' +
        '<div class="preview-meta">检测到渠道: <span class="channel-tag">' + (preview.ota.detected_channel || "未知") + '</span></div>' +
        '<div class="preview-headers">表头: ' + preview.ota.headers.join(", ") + '</div>' +
        '</div>';
    }
    if (preview.pms) {
      pmsHtml = '<div class="preview-card-inner">' +
        '<div class="preview-title">PMS报表</div>' +
        '<div class="preview-meta">文件名: ' + preview.pms.filename + '</div>' +
        '<div class="preview-meta">工作表: ' + preview.pms.sheet + '</div>' +
        '<div class="preview-meta">数据行: ' + preview.pms.rows + ' 行</div>' +
        '<div class="preview-meta">格式验证: ' + (preview.pms.is_rezen ? "✅ 标准Rezen格式" : "⚠️ 非标准格式") + '</div>' +
        '<div class="preview-headers">表头: ' + preview.pms.headers.join(", ") + '</div>' +
        '</div>';
    }
    document.getElementById("otaPreviewOta").innerHTML = otaHtml;
    document.getElementById("otaPreviewPms").innerHTML = pmsHtml;
  }

  window.otaBackToUpload = function() {
    showOtaStep(1);
    document.getElementById("otaFile").value = "";
    document.getElementById("pmsFile").value = "";
    document.getElementById("otaPathHint").textContent = "";
    document.getElementById("pmsPathHint").textContent = "";
    window._otaState = { otaPath: "", pmsPath: "", channel: "", matchData: null };
  };

  // Step 2 -> 3: 执行匹配
  window.runOtaMatch = async function() {
    var btn = document.getElementById("otaMatchBtn");
    btnDisable(btn, "匹配中...");
    try {
      var resp = await apiPost("/ota/match_preview", {
        ota_path: window._otaState.otaPath,
        pms_path: window._otaState.pmsPath
      });
      if (!resp.ok) { setResult("otaResult", "匹配失败：" + (resp.detail || "未知")); btnEnable(btn, "确认并开始匹配"); return; }

      window._otaState.channel = resp.channel;
      window._otaState.matchData = resp.details;
      window._otaState.matchResults = resp.raw_results || [];
      window._otaState.matchStats = resp.stats || {};
      renderOtaMatchResults(resp.stats, resp.details);
      showOtaStep(3);
    } catch(e) { setResult("otaResult", "错误：" + e.message); }
    btnEnable(btn, "确认并开始匹配");
  };

  function renderOtaMatchResults(stats, details) {
    var summaryHtml = '<div class="match-summary-grid">' +
      '<div class="match-stat"><span class="stat-num">' + stats.total_ota + '</span><span class="stat-label">OTA记录</span></div>' +
      '<div class="match-stat"><span class="stat-num">' + stats.total_pms + '</span><span class="stat-label">PMS记录</span></div>' +
      '<div class="match-stat success"><span class="stat-num">' + stats.match + '</span><span class="stat-label">匹配成功</span></div>' +
      '<div class="match-stat danger"><span class="stat-num">' + stats.diff + '</span><span class="stat-label">金额差异</span></div>' +
      '<div class="match-stat warning"><span class="stat-num">' + stats.ota_only + '</span><span class="stat-label">仅OTA</span></div>' +
      '<div class="match-stat info"><span class="stat-num">' + stats.pms_only + '</span><span class="stat-label">仅PMS</span></div>' +
      '</div>';
    document.getElementById("otaMatchSummary").innerHTML = summaryHtml;

    document.getElementById("tabCountMatch").textContent = details.match.length;
    document.getElementById("tabCountDiff").textContent = details.diff.length;
    document.getElementById("tabCountOta").textContent = details.ota_only.length;
    document.getElementById("tabCountPms").textContent = details.pms_only.length;

    switchOtaTab('match', document.querySelector('.ota-match-tabs .tab-btn'));
  }

  window.switchOtaTab = function(tabName, clickedBtn) {
    document.querySelectorAll(".ota-match-tabs .tab-btn").forEach(function(btn) {
      btn.classList.remove("active");
    });
    if (clickedBtn) {
      clickedBtn.classList.add("active");
    } else if (event && event.target) {
      event.target.classList.add("active");
    }

    var data = window._otaState.matchData;
    if (!data) return;
    var items = data[tabName] || [];
    var html = '';

    if (items.length === 0) {
      html = '<div class="card-empty">该分类下无记录</div>';
    } else {
      html = '<table class="card-table">' +
        '<thead><tr>' +
        '<th>OTA订单号</th><th>PMS订单号</th><th>OTA金额</th><th>PMS金额</th><th>差额</th><th>状态</th>' +
        '</tr></thead><tbody>';
      for (var i = 0; i < items.length; i++) {
        var r = items[i];
        var statusClass = r.status === 'match' ? 'status-ok' : (r.status === 'diff' ? 'status-diff' : '');
        var statusText = r.status === 'match' ? '匹配' : (r.status === 'diff' ? '差异' : (r.status === 'ota_only' ? '仅OTA' : '仅PMS'));
        html += '<tr>' +
          '<td>' + (r.ota_order || '-') + '</td>' +
          '<td>' + (r.pms_ext_order || '-') + '</td>' +
          '<td>' + (r.ota_amount ? r.ota_amount.toFixed(2) : '-') + '</td>' +
          '<td>' + (r.pms_amount ? r.pms_amount.toFixed(2) : '-') + '</td>' +
          '<td>' + (r.diff ? r.diff.toFixed(2) : '-') + '</td>' +
          '<td class="' + statusClass + '">' + statusText + '</td>' +
          '</tr>';
      }
      html += '</tbody></table>';
    }
    document.getElementById("otaMatchContent").innerHTML = html;
  };

  window.otaBackToPreview = function() {
    showOtaStep(2);
  };

  // Step 3 -> 4: 进入差异确认
  window.goToOtaDiffConfirm = function() {
    var data = window._otaState.matchData;
    if (!data) return;
    var diffItems = data.diff || [];
    var otaOnlyItems = data.ota_only || [];
    var pmsOnlyItems = data.pms_only || [];
    var allIssues = diffItems.concat(otaOnlyItems).concat(pmsOnlyItems);

    var html = '';
    if (allIssues.length === 0) {
      html = '<div class="card-empty">🎉 无差异记录，所有订单已对平</div>';
    } else {
      html = '<table class="card-table">' +
        '<thead><tr><th>核实</th><th>类型</th><th>OTA订单号</th><th>PMS订单号</th><th>OTA金额</th><th>PMS金额</th><th>差额</th></tr></thead><tbody>';
      for (var i = 0; i < allIssues.length; i++) {
        var r = allIssues[i];
        var typeText = r.status === 'diff' ? '金额差异' : (r.status === 'ota_only' ? '仅OTA存在' : '仅PMS存在');
        html += '<tr>' +
          '<td><input type="checkbox" class="ota-check" data-id="' + r.id + '" checked></td>' +
          '<td>' + typeText + '</td>' +
          '<td>' + (r.ota_order || '-') + '</td>' +
          '<td>' + (r.pms_ext_order || '-') + '</td>' +
          '<td>' + (r.ota_amount ? r.ota_amount.toFixed(2) : '-') + '</td>' +
          '<td>' + (r.pms_amount ? r.pms_amount.toFixed(2) : '-') + '</td>' +
          '<td>' + (r.diff ? r.diff.toFixed(2) : '-') + '</td>' +
          '</tr>';
      }
      html += '</tbody></table>';
    }
    document.getElementById("otaDiffList").innerHTML = html;
    showOtaStep(4);
  };

  window.otaBackToMatch = function() {
    showOtaStep(3);
  };

  // Step 4 -> 5: 确认并生成报告
  window.runOtaConfirm = async function() {
    var btn = document.getElementById("otaConfirmBtn");
    btnDisable(btn, "生成中...");
    try {
      var checks = document.querySelectorAll(".ota-check");
      var confirmedItems = [];
      for (var i = 0; i < checks.length; i++) {
        if (checks[i].checked) confirmedItems.push(checks[i].dataset.id);
      }
      var comment = document.getElementById("otaComment").value.trim();

      var resp = await apiPost("/ota/confirm", {
        ota_path: window._otaState.otaPath,
        pms_path: window._otaState.pmsPath,
        channel: window._otaState.channel,
        confirmed_matches: [],
        confirmed_diffs: confirmedItems,
        comments: comment,
        match_results: window._otaState.matchResults || [],
        stats: window._otaState.matchStats || {}
      });

      if (resp.ok) {
        var resultHtml = '<div class="ota-result-ok">' +
          '<h3>✅ 对账报告已生成</h3>' +
          '<div class="result-item">渠道: ' + resp.channel + '</div>' +
          '<div class="result-item">报告路径: ' + resp.report_path + '</div>' +
          '<div class="result-item">匹配: ' + resp.stats.match + ' | 差异: ' + resp.stats.diff + ' | 仅OTA: ' + resp.stats.ota_only + ' | 仅PMS: ' + resp.stats.pms_only + '</div>' +
          '<div class="result-item">已确认差异项: ' + resp.confirmed.diffs + '</div>' +
          (comment ? '<div class="result-item">批注: ' + comment + '</div>' : '') +
          '</div>';
        document.getElementById("otaResultSection").innerHTML = resultHtml;
        showOtaStep(5);
      } else {
        setResult("otaResult", "生成失败：" + (resp.detail || "未知"));
      }
    } catch(e) { setResult("otaResult", "错误：" + e.message); }
    btnEnable(btn, "确认并生成报告");
  };

  window.otaReset = function() {
    showOtaStep(1);
    document.getElementById("otaFile").value = "";
    document.getElementById("pmsFile").value = "";
    document.getElementById("otaPathHint").textContent = "";
    document.getElementById("pmsPathHint").textContent = "";
    document.getElementById("otaComment").value = "";
    document.getElementById("otaResultSection").innerHTML = "";
    window._otaState = { otaPath: "", pmsPath: "", channel: "", matchData: null };
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
  window._cardState = { bankPath: "", pmsPath: "", unmatched: [] };

  window.updateCardPath = function(inputId, hintId) {
    var f = document.getElementById(inputId).files[0];
    document.getElementById(hintId).textContent = f ? f.name : "";
  };

  window.runCardPreview = async function() {
    var btn = document.getElementById("cardPreviewBtn");
    btnDisable(btn, "对账中...");
    setResult("cardResult", "");
    try {
      var bank = await uploadAndGetPath("bankFile");
      var pms = await uploadAndGetPath("pmsCardFile");
      if (!bank || !pms) {
        setResult("cardResult", "错误：请上传两个文件");
        btnEnable(btn, "开始对账");
        return;
      }
      window._cardState.bankPath = bank;
      window._cardState.pmsPath = pms;

      var resp = await apiPost("/card/recon_preview", { bank_statement_path: bank, pms_card_path: pms });
      if (!resp.ok) {
        setResult("cardResult", "错误：" + (resp.detail || "未知"));
        btnEnable(btn, "开始对账");
        return;
      }

      renderCardPreview(resp.summary, resp.unmatched_details);
      document.getElementById("cardStep1").style.display = "none";
      document.getElementById("cardStep2").style.display = "block";
    } catch(e) {
      setResult("cardResult", "错误：" + e.message);
    }
    btnEnable(btn, "开始对账");
  };

  function renderCardPreview(summary, unmatched) {
    window._cardState.unmatched = unmatched || [];
    window._cardState.reconResults = summary || [];

    var summaryHtml = '<h3>对账汇总</h3><table class="card-table">' +
      '<thead><tr><th>付款方式</th><th>PMS数量</th><th>POS数量</th><th>PMS金额</th><th>POS金额</th><th>差额</th><th>状态</th></tr></thead><tbody>';
    for (var i = 0; i < summary.length; i++) {
      var s = summary[i];
      var statusClass = s.balanced ? "status-ok" : "status-diff";
      var statusText = s.balanced ? "对平" : "差异";
      summaryHtml += '<tr>' +
        '<td>' + s.channel + '</td>' +
        '<td>' + s.pms_count + '</td>' +
        '<td>' + s.bank_count + '</td>' +
        '<td>' + s.pms_total.toFixed(2) + '</td>' +
        '<td>' + s.bank_total.toFixed(2) + '</td>' +
        '<td>' + s.diff.toFixed(2) + '</td>' +
        '<td class="' + statusClass + '">' + statusText + '</td>' +
        '</tr>';
    }
    summaryHtml += '</tbody></table>';
    document.getElementById("cardSummary").innerHTML = summaryHtml;

    var listHtml = '';
    if (unmatched && unmatched.length > 0) {
      listHtml += '<table class="card-table">' +
        '<thead><tr><th>核实</th><th>付款方式</th><th>来源</th><th>差异类型</th><th>金额</th><th>原始数据</th></tr></thead><tbody>';
      for (var j = 0; j < unmatched.length; j++) {
        var u = unmatched[j];
        var rawStr = JSON.stringify(u.raw).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
        listHtml += '<tr>' +
          '<td><input type="checkbox" class="card-check" data-id="' + u.id + '" checked></td>' +
          '<td>' + u.channel + '</td>' +
          '<td>' + u.source + '</td>' +
          '<td>' + u.type + '</td>' +
          '<td>' + (u.amount ? u.amount.toFixed(2) : "0.00") + '</td>' +
          '<td class="raw-cell" title="' + rawStr + '">' + rawStr + '</td>' +
          '</tr>';
      }
      listHtml += '</tbody></table>';
    } else {
      listHtml = '<div class="card-empty">无差异明细，所有款项已对平</div>';
    }
    document.getElementById("cardUnmatchedList").innerHTML = listHtml;
    document.getElementById("cardComment").value = "";
  }

  window.cardBackToUpload = function() {
    document.getElementById("cardStep1").style.display = "block";
    document.getElementById("cardStep2").style.display = "none";
    setResult("cardResult", "");
  };

  window.runCardConfirm = async function() {
    var btn = document.getElementById("cardConfirmBtn");
    btnDisable(btn, "生成中...");
    try {
      var checks = document.querySelectorAll(".card-check");
      var reviewItems = [];
      for (var i = 0; i < checks.length; i++) {
        if (checks[i].checked) {
          reviewItems.push(checks[i].dataset.id);
        }
      }
      var comment = document.getElementById("cardComment").value.trim();
      var resp = await apiPost("/card/recon_confirm", {
        bank_statement_path: window._cardState.bankPath,
        pms_card_path: window._cardState.pmsPath,
        review_items: reviewItems,
        comments: comment,
        recon_results: window._cardState.reconResults || []
      });
      if (resp.ok) {
        setResult("cardResult", "审核完成\n已核实项: " + resp.reviewed_count + "\n批注: " + (resp.comments || "无") + "\n\n" + resp.result);
        document.getElementById("cardStep2").style.display = "none";
        document.getElementById("cardStep1").style.display = "block";
        document.getElementById("bankFile").value = "";
        document.getElementById("pmsCardFile").value = "";
        document.getElementById("bankPathHint").textContent = "";
        document.getElementById("pmsCardPathHint").textContent = "";
      } else {
        setResult("cardResult", "错误：" + (resp.detail || "未知"));
      }
    } catch(e) {
      setResult("cardResult", "错误：" + e.message);
    }
    btnEnable(btn, "确认并生成报告");
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

  // ===== Approval Queue (审批队列) =====
  window._approvalState = { filter: 'all', items: [] };

  window.loadApprovalQueue = async function() {
    var section = document.getElementById("approvalQueueSection");
    section.style.display = "block";

    try {
      // 加载统计
      var statsResp = await fetch(API + "/scheduler/stats");
      var statsData = await statsResp.json();
      if (statsData.ok && statsData.stats) {
        document.getElementById("statPending").textContent = statsData.stats.pending || 0;
        document.getElementById("statApproved").textContent = statsData.stats.approved || 0;
        document.getElementById("statRejected").textContent = statsData.stats.rejected || 0;
      }

      // 加载队列
      var queueResp = await fetch(API + "/scheduler/approvals");
      var queueData = await queueResp.json();
      if (queueData.ok) {
        window._approvalState.items = queueData.items || [];
        renderApprovalList();
      }
    } catch(e) {
      document.getElementById("approvalList").innerHTML = '<div class="approval-empty">加载失败: ' + e.message + '</div>';
    }
  };

  window.filterApprovals = function(status) {
    window._approvalState.filter = status;
    // 更新按钮状态
    document.querySelectorAll('.approval-filters .btn-sm').forEach(function(btn) {
      btn.classList.remove('active');
    });
    event.target.classList.add('active');
    renderApprovalList();
  };

  function renderApprovalList() {
    var container = document.getElementById("approvalList");
    var items = window._approvalState.items;
    var filter = window._approvalState.filter;

    if (filter !== 'all') {
      items = items.filter(function(item) { return item.status === filter; });
    }

    if (items.length === 0) {
      container.innerHTML = '<div class="approval-empty">暂无审批记录</div>';
      return;
    }

    var html = '';
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var statusClass = item.status === 'pending' ? 'pending' : (item.status === 'approved' ? 'approved' : 'rejected');
      var statusText = item.status === 'pending' ? '待复核' : (item.status === 'approved' ? '已通过' : '已驳回');
      var confidencePercent = Math.round((item.confidence || 0) * 100);
      var confidenceClass = confidencePercent >= 80 ? 'high' : (confidencePercent >= 50 ? 'medium' : 'low');

      html += '<div class="approval-item ' + statusClass + '">' +
        '<div class="approval-header">' +
          '<span class="approval-id">' + item.id + '</span>' +
          '<span class="approval-status ' + statusClass + '">' + statusText + '</span>' +
        '</div>' +
        '<div class="approval-body">' +
          '<div class="approval-task">任务: ' + item.task_name + '</div>' +
          '<div class="approval-confidence ' + confidenceClass + '">置信度: ' + confidencePercent + '%</div>' +
          '<div class="approval-output">' + (item.output || '').substring(0, 200) + '</div>' +
          '<div class="approval-time">创建: ' + item.created_at + '</div>' +
        '</div>';

      html += '<div class="approval-actions">';
      if (item.status === 'pending') {
        html += '<button class="btn-xs btn-success" onclick="handleApproval(\'' + item.id + '\', \'approve\')">通过</button>' +
          '<button class="btn-xs btn-danger" onclick="handleApproval(\'' + item.id + '\', \'reject\')">驳回</button>' +
          '<input type="text" class="approval-note-input" placeholder="添加备注..." id="note-' + item.id + '">';
      } else {
        html += '<span class="approval-resolved">处理: ' + (item.resolved_at || '-') +
          (item.note ? ' | 备注: ' + item.note : '') + '</span>';
      }
      html += '<button class="btn-xs btn-secondary" onclick="deleteApproval(\'' + item.id + '\')" title="删除">🗑️</button>' +
        '</div>';

      html += '</div>';
    }
    container.innerHTML = html;
  }

  window.handleApproval = async function(approvalId, action) {
    var noteInput = document.getElementById("note-" + approvalId);
    var note = noteInput ? noteInput.value.trim() : "";

    try {
      var resp = await fetch(API + "/scheduler/approvals/" + approvalId + "/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id: approvalId, action: action, note: note })
      });
      var data = await resp.json();
      if (data.ok) {
        // 刷新列表
        loadApprovalQueue();
      } else {
        alert("操作失败: " + (data.detail || "未知"));
      }
    } catch(e) {
      alert("操作失败: " + e.message);
    }
  };

  window.deleteApproval = async function(approvalId) {
    if (!confirm("确定要删除该审批项吗？")) return;

    try {
      var resp = await fetch(API + "/scheduler/approvals/" + approvalId, {
        method: "DELETE"
      });
      var data = await resp.json();
      if (data.ok) {
        loadApprovalQueue();
      } else {
        alert("删除失败: " + (data.detail || "未知"));
      }
    } catch(e) {
      alert("删除失败: " + e.message);
    }
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