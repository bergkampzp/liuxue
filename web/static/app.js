/**
 * 选校罗盘 — app.js
 * ES module, ~260 行
 * W-T4: index 首页定位 + 四态渲染 + waitlist 钩子
 * W-T5 stub: renderLadder（school.html 全景表，待实现）
 */

// ── 常量 ──────────────────────────────────────────────────────
const API_BASE = "";

/** 前端追加的积累中校（/position 不返回时固定灰行） */
const PENDING_SCHOOLS = [
  { uk_uni_id: "manchester", name_zh: "曼彻斯特大学" },
  { uk_uni_id: "kcl",        name_zh: "伦敦国王学院" },
];

/** tier → emoji */
const TIER_EMOJI = { "冲": "🚀", "匹": "🎯", "保": "✅", "不建议": "⚠️" };

/** tier 排序顺序 */
const TIER_ORDER = ["冲", "匹", "保", "不建议"];

/** source_type → badge class + label */
const BADGE_BY_SOURCE = {
  official_web: { cls: "badge-official", label: "官方公布" },
  official_pdf: { cls: "badge-official", label: "官方公布" },
  aggregator:   { cls: "badge-ref",      label: "参考线·待核" },
  case_inferred:{ cls: "badge-ref",      label: "参考线·待核" },
};

// ── XSS 防护 ─────────────────────────────────────────────────
/**
 * 将任意字符串转为安全的 textContent（防 XSS）。
 * 所有来自 API 的字符串都必须经过本函数后才能插入 HTML。
 */
function esc(s) {
  if (s == null) return "";
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

// ── API 封装 ─────────────────────────────────────────────────
/**
 * 通用 fetch，10 秒超时。
 * 422 → throw { kind: "unrecognized", msg, hint }
 * 其他失败 → throw { kind: "unavailable" }
 */
async function api(path, { method = "GET", body } = {}) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), 10_000);
  try {
    const res = await fetch(API_BASE + path, {
      method,
      signal: ctrl.signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.ok) return res.json();

    if (res.status === 422) {
      let detail;
      try { detail = (await res.json()).detail; } catch { detail = null; }
      // detail 可能是 dict 或字符串，都兼容
      const msg  = (detail && typeof detail === "object" ? detail.msg  : detail) || "未识别的请求";
      const hint = (detail && typeof detail === "object" ? detail.hint : "")    || "";
      throw { kind: "unrecognized", msg, hint };
    }
    throw { kind: "unavailable" };
  } catch (err) {
    clearTimeout(tid);
    if (err && err.kind) throw err;
    throw { kind: "unavailable" };
  } finally {
    clearTimeout(tid);
  }
}

// ── Toast ────────────────────────────────────────────────────
let _toastTimer = null;
function toast(msg, ms = 3200) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}

// ── 表单校验 ─────────────────────────────────────────────────
/**
 * 校验 #position-form，失败时给对应 .field 加 .invalid + toast。
 * 成功返回 /position 请求体，失败返回 null。
 */
function validatePosition(form) {
  // 清除上次校验状态
  form.querySelectorAll(".invalid").forEach(el => el.classList.remove("invalid"));

  const schoolEl   = form.elements["school"];
  const scoreEl    = form.elements["score"];
  const subjectEl  = form.elements["subject"];
  const ieltsEl    = form.elements["ielts"];

  const school  = (schoolEl.value  || "").trim();
  const scoreRaw= (scoreEl.value   || "").trim();
  const subject = (subjectEl.value || "").trim();
  const ieltsRaw= (ieltsEl.value   || "").trim();

  // 校名 ≥ 2 字符
  if (school.length < 2) {
    schoolEl.classList.add("invalid");
    toast("请输入完整的本科学校名称（至少 2 个字符）");
    return null;
  }

  // 均分 40-100
  const score = parseFloat(scoreRaw);
  if (!scoreRaw || isNaN(score) || score < 40 || score > 100) {
    scoreEl.classList.add("invalid");
    toast("均分需在 40 到 100 之间");
    return null;
  }

  // 雅思选填：若有值则 0-9 且 0.5 步进
  let ielts_overall = undefined;
  if (ieltsRaw) {
    const ielts = parseFloat(ieltsRaw);
    if (isNaN(ielts) || ielts < 0 || ielts > 9 || (ielts * 2) % 1 !== 0) {
      ieltsEl.classList.add("invalid");
      toast("雅思总分需在 0–9 之间，且为 0.5 的倍数（如 6.5）");
      return null;
    }
    ielts_overall = ielts;
  }

  const body = {
    undergrad_school:   school,
    avg_score:          score,
    undergrad_major:    subject,
    tgt_subject_group:  subject,
  };
  if (ielts_overall !== undefined) body.ielts_overall = ielts_overall;
  return body;
}

// ── Waitlist 行内微表单 ───────────────────────────────────────
/**
 * 为⏳积累中行绑定 waitlist 微表单。
 * 点击"留个邮箱" → 行内展开 email input + 提交按钮
 * → POST /waitlist → 成功替换为提示文字
 */
function bindWaitlist(rowEl, uk_uni_id, profile) {
  const trigger = rowEl.querySelector(".waitlist-trigger");
  if (!trigger) return;

  trigger.addEventListener("click", (e) => {
    e.preventDefault();
    // 已展开则不重复
    if (rowEl.querySelector(".waitlist-form")) return;

    const wrap = document.createElement("span");
    wrap.className = "waitlist-form";
    wrap.style.cssText = "display:inline-flex;gap:6px;align-items:center;margin-left:6px";

    const emailInput = document.createElement("input");
    emailInput.type = "email";
    emailInput.placeholder = "your@email.com";
    emailInput.style.cssText =
      "font-size:11px;padding:3px 8px;border:1px solid #d4d4d8;border-radius:8px;outline:none;font-family:inherit";

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.textContent = "登记";
    submitBtn.style.cssText =
      "font-size:11px;padding:3px 10px;background:var(--grad-cta);color:#fff;" +
      "border:none;border-radius:8px;cursor:pointer;font-family:inherit;font-weight:600";

    submitBtn.addEventListener("click", async () => {
      if (!emailInput.checkValidity() || !emailInput.value.trim()) {
        emailInput.style.borderColor = "#ef4444";
        toast("请输入有效的邮箱地址");
        return;
      }
      submitBtn.disabled = true;
      try {
        await api("/waitlist", {
          method: "POST",
          body: { email: emailInput.value.trim(), uk_uni_id, profile },
        });
        wrap.replaceWith(document.createTextNode("已登记，上线后第一时间通知你"));
      } catch {
        toast("登记失败，请稍后再试");
        submitBtn.disabled = false;
      }
    });

    wrap.appendChild(emailInput);
    wrap.appendChild(submitBtn);
    trigger.replaceWith(wrap);
  });
}

// ── 渲染定位结果 ─────────────────────────────────────────────
/**
 * 将 /position 返回数据渲染到 #results。
 * @param {object} data   - API 响应
 * @param {object} query  - { school, score, subject } 用于生成标题
 */
function renderPosition(data, query) {
  const resultsEl = document.getElementById("results");
  if (!resultsEl) return;

  const { schools = [], not_on_list = [], major_fit, waitlist_hint } = data;

  // 已出现在结果中的 uk_uni_id 集合（用于 PENDING_SCHOOLS 去重）
  const appearedIds = new Set([
    ...schools.map(s => s.uk_uni_id),
    ...not_on_list.map(s => s.uk_uni_id),
  ]);

  // 按 TIER_ORDER 分桶（桶内保持 API 序）
  const buckets = {};
  for (const t of TIER_ORDER) buckets[t] = [];
  for (const s of schools) {
    if (buckets[s.tier]) buckets[s.tier].push(s);
    else buckets["不建议"].push(s);  // 未知 tier 归入不建议
  }

  // 构建行 HTML
  let rowsHtml = "";

  // major_fit 顶部条（11px --gray）
  if (major_fit) {
    const fitLevel = esc(major_fit.fit_level);
    const src      = esc(major_fit.src_major_category);
    let fitText;
    if (major_fit.fit_level === "未知方向") {
      fitText = `专业适配：${src} → 该转申方向暂无规则判定，建议人工咨询`;
    } else {
      fitText = `专业适配：${src} → 目标方向 ${fitLevel}`;
      if (major_fit.required_prereqs) {
        fitText += `；前置要求：${esc(major_fit.required_prereqs)}`;
      }
    }
    rowsHtml += `<div style="font-size:11px;color:var(--gray);padding:8px 4px 4px;border-bottom:1px solid var(--line-soft)">${fitText}</div>`;
  }

  // 冲/匹/保/不建议 各桶
  for (const tier of TIER_ORDER) {
    const isDim = tier === "不建议";
    for (const s of buckets[tier]) {
      const badge    = BADGE_BY_SOURCE[s.source_type] || { cls: "badge-pending", label: "案例积累中" };
      const emoji    = TIER_EMOJI[s.tier] || "📌";
      const sourceHtml = s.source_url
        ? `<a class="row-source" href="${esc(s.source_url)}" target="_blank" rel="noopener">来源 ↗</a>`
        : "";
      rowsHtml += `
<div class="result-row${isDim ? " is-dim" : ""}">
  <span class="row-emoji">${emoji}</span>
  <div class="row-main">
    <div class="row-title">${esc(s.name_zh)} <span class="badge ${badge.cls}">${badge.label}</span></div>
    <div class="row-sub">${esc(s.explanation)}</div>
  </div>
  ${sourceHtml}
</div>`;
    }
  }

  // not_on_list：⛔ 红行 is-dim
  for (const s of not_on_list) {
    const sourceHtml = s.source_url
      ? `<a class="row-source" href="${esc(s.source_url)}" target="_blank" rel="noopener">名单 ↗</a>`
      : "";
    rowsHtml += `
<div class="result-row is-dim">
  <span class="row-emoji">⛔</span>
  <div class="row-main">
    <div class="row-title">${esc(s.name_zh)} <span class="badge badge-notlist">不在认可名单</span></div>
    <div class="row-sub">${esc(s.note)}</div>
  </div>
  ${sourceHtml}
</div>`;
  }

  // PENDING_SCHOOLS：未在结果中的 → ⏳ 灰行 + waitlist 微表单
  const pendingProfile = { school: query.school, score: query.score, subject: query.subject };
  for (const p of PENDING_SCHOOLS) {
    if (appearedIds.has(p.uk_uni_id)) continue;
    rowsHtml += `
<div class="result-row is-dim" data-pending="${esc(p.uk_uni_id)}">
  <span class="row-emoji">⏳</span>
  <div class="row-main">
    <div class="row-title">${esc(p.name_zh)} <span class="badge badge-pending">案例积累中</span></div>
    <div class="row-sub">精确线尚未收录；案例积累中，上线后第一时间通知你——<a href="#" class="waitlist-trigger" style="color:var(--violet);text-decoration:underline">留个邮箱</a></div>
  </div>
</div>`;
  }

  // 一次性替换 innerHTML
  resultsEl.innerHTML = `
<div class="results-label">你的定位 — ${esc(query.school)} · 均分 ${esc(String(query.score))} · ${esc(query.subject)}</div>
${rowsHtml}`;

  // 绑定 waitlist 钩子
  for (const p of PENDING_SCHOOLS) {
    if (appearedIds.has(p.uk_uni_id)) continue;
    const rowEl = resultsEl.querySelector(`[data-pending="${p.uk_uni_id}"]`);
    if (rowEl) bindWaitlist(rowEl, p.uk_uni_id, pendingProfile);
  }

  // 滚动到结果区
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── W-T5: renderLadder ───────────────────────────────────────
/**
 * 渲染 /school-ladder 全景表到 #ladder-result。
 * @param {object} data - API 响应 { cn_university, schools, disclaimer }
 */
function renderLadder(data) {
  const el = document.getElementById("ladder-result");
  if (!el) return;

  const { cn_university = {}, schools = [] } = data;

  // 空数组兜底
  if (!schools.length) {
    el.innerHTML = `<div class="results-label">该校已识别，但暂无可展示的名单记录</div>`;
    return;
  }

  // 顶部标签
  const labelHtml = `<div class="results-label">${esc(cn_university.name_zh || "")}（${esc(cn_university.tier_label || "")}）— 在 30 所英国大学的待遇全景</div>`;

  // 表头
  const headHtml = `
<div class="ladder-head">
  <span>英国大学</span>
  <span>QS 排名</span>
  <span>名单状态</span>
  <span>分数线</span>
  <span>雅思</span>
  <span>出处</span>
</div>`;

  // 行
  let rowsHtml = "";
  for (const s of schools) {
    // 徽章逻辑
    let badgeCls, badgeLabel;
    const ls = s.list_status || "";
    if (ls.startsWith("名单内")) {
      badgeCls   = "badge-official";
      badgeLabel = esc(ls);
    } else if (ls === "有分数线") {
      const src = s.source_type || "";
      if (src.startsWith("official")) {
        badgeCls   = "badge-official";
        badgeLabel = "官方公布";
      } else {
        badgeCls   = "badge-ref";
        badgeLabel = "参考线·待核";
      }
    } else if (ls === "不在认可名单") {
      badgeCls   = "badge-notlist";
      badgeLabel = "不在认可名单";
    } else if (ls === "未收录") {
      badgeCls   = "badge-pending";
      badgeLabel = "案例积累中";
    } else if (ls === "个案审核") {
      badgeCls   = "badge-pending";
      badgeLabel = "个案审核";
    } else {
      badgeCls   = "badge-pending";
      badgeLabel = esc(ls);
    }

    // dim 行
    const isDim = ls === "不在认可名单" || ls === "未收录";

    // QS
    const qsHtml = s.qs_rank != null ? `#${esc(String(s.qs_rank))}` : "—";

    // 分数线
    let scoreHtml = "—";
    if (s.min_avg_score != null) {
      const src = s.source_type || "";
      const suffix = src.startsWith("official") ? "" : "（参考）";
      scoreHtml = `${esc(String(s.min_avg_score))}${suffix}`;
      // 谢菲且 band_min_score 非空 → 追加小字
      if (s.uk_uni_id === "sheffield" && s.band_min_score != null) {
        scoreHtml += `<br><span style="font-size:10px;color:var(--muted)">逐校档线 ${esc(String(s.band_min_score))}</span>`;
      }
    }

    // 雅思
    const ieltsHtml = s.ielts_overall != null ? esc(String(s.ielts_overall)) : "—";

    // 出处
    const srcHtml = s.source_url
      ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener">出处 ↗</a>`
      : "—";

    rowsHtml += `
<div class="ladder-row${isDim ? " is-dim" : ""}">
  <span class="lr-name">${esc(s.name_zh)}</span>
  <span class="lr-qs" data-label="QS 排名">${qsHtml}</span>
  <span class="lr-status" data-label="名单状态"><span class="badge ${badgeCls}">${badgeLabel}</span></span>
  <span class="lr-score" data-label="你这档分数线">${scoreHtml}</span>
  <span class="lr-ielts" data-label="雅思基线">${ieltsHtml}</span>
  <span class="lr-src" data-label="出处">${srcHtml}</span>
</div>`;
  }

  el.innerHTML = labelHtml + headHtml + rowsHtml;
}

// ── 入口：绑定表单 ────────────────────────────────────────────
const positionForm = document.getElementById("position-form");
if (positionForm) {
  positionForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = validatePosition(positionForm);
    if (!body) return;

    const btn = positionForm.querySelector(".btn-cta");
    if (btn) btn.disabled = true;

    try {
      const data = await api("/position", { method: "POST", body });
      renderPosition(data, {
        school:  body.undergrad_school,
        score:   body.avg_score,
        subject: body.tgt_subject_group,
      });
    } catch (err) {
      if (err && err.kind === "unrecognized") {
        const hint = err.hint ? `\n${err.hint}` : "";
        toast(`${err.msg}${hint}`);
      } else {
        toast("服务暂时不可用，请稍后再试");
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

const ladderForm = document.getElementById("ladder-form");
if (ladderForm) {
  ladderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const schoolEl = ladderForm.elements["school"];
    const v = (schoolEl.value || "").trim();
    if (v.length < 2) {
      schoolEl.classList.add("invalid");
      toast("请输入完整的学校名称（至少 2 个字符）");
      return;
    }
    schoolEl.classList.remove("invalid");

    const btn = ladderForm.querySelector(".btn-cta");
    if (btn) btn.disabled = true;

    try {
      const data = await api("/school-ladder?school=" + encodeURIComponent(v));
      renderLadder(data);
    } catch (err) {
      if (err && err.kind === "unrecognized") {
        const hint = err.hint ? `\n${err.hint}` : "";
        toast(`${err.msg}${hint}`);
      } else {
        toast("服务暂时不可用，请稍后再试");
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}
