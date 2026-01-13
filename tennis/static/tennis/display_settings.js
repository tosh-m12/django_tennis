// tennis/static/tennis/display_settings.js
// ============================================================
// Display Settings (Single Source of Truth / 最終版)
//
// ✅ event page：DBが唯一の正（localStorageは絶対に参照しない）
//   - load : #page-hooks[data-display-settings] を読む（db/defaultどちらもサーバ値）
//   - save : POST to #page-hooks[data-save-display-settings-url]（DB保存）
//   - apply: 常にサーバ値で描画（別端末でも一致）
//
// ✅ club-event-modal（イベント作成/編集モーダル）：localStorageは「下書き」用
//   - event_id 無し：draft を localStorage に保存 + hidden field にも書く
//   - event_id 有り：★このJSではDB保存しない（裏更新させない）
//     → DBへ反映するのは「イベント編集モーダルの更新ボタン」を押したときのみ
//
// ✅ create直後：draft を 1回だけDBへ移植（サーバにまだ設定が無い時だけ）
//   - 作成モーダルの設定がイベントページに引き継がれ、他端末にも伝播
//
// 重要：
// - event page は localStorage を一切読まない
// - localStorage は club-event-modal の draft のみ
// - club-event-modal 文脈で表示設定OKを押しても “絶対に” /ajax/save_event_display_setting/ を叩かない
// ============================================================

(function () {
  // ============================================================
  // 0) Keys (localStorage) - ★draftのみ運用
  // ============================================================
  function storageKeyDraft() {
    return `tennis:display_settings:draft:club_event_modal`;
  }

  // ============================================================
  // 1) Utils
  // ============================================================
  function safeJsonParse(raw, fallback) {
    if (!raw) return fallback;

    try {
      return JSON.parse(raw);
    } catch {}

    try {
      let fixed = String(raw);
      fixed = fixed.replace(/\\u0022/g, '"');
      fixed = fixed.replace(/&quot;/g, '"');
      fixed = fixed.replace(/&amp;quot;/g, '"');
      return JSON.parse(fixed);
    } catch {
      console.warn("[DS] JSON parse failed even after fix", { raw });
      return fallback;
    }
  }

  function defaultSettings() {
    return {
      common_flags: true,
      event_flags: false,
      class: true,
      schedule: true,
    };
  }

  // 互換：旧キーも受け入れて「新キーへ正規化」
  function normalizeSettings(obj) {
    const d = defaultSettings();
    if (!obj || typeof obj !== "object") return d;

    const hasNew =
      ("common_flags" in obj) ||
      ("event_flags" in obj) ||
      ("class" in obj) ||
      ("schedule" in obj);

    if (hasNew) {
      return {
        common_flags: obj.common_flags !== false,
        event_flags: obj.event_flags === true, // default=false → trueのみtrue
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    const hasOldSimple =
      ("flags" in obj) || ("class" in obj) || ("schedule" in obj);
    if (hasOldSimple) {
      return {
        common_flags: obj.flags !== false,
        event_flags: true, // 旧には無い → ON寄せ
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    const hasOldShow =
      ("show_flags" in obj) || ("show_class" in obj) || ("show_schedule" in obj);
    if (hasOldShow) {
      return {
        common_flags: obj.show_flags !== false,
        event_flags: true,
        class: obj.show_class !== false,
        schedule: obj.show_schedule !== false,
      };
    }

    return d;
  }

  // ============================================================
  // 2) localStorage (draft only)
  // ============================================================
  function loadDraft() {
    const raw = safeJsonParse(localStorage.getItem(storageKeyDraft()), {});
    if (raw && typeof raw === "object" && ("flags" in raw) && !("common_flags" in raw)) {
      raw.common_flags = raw.flags !== false;
    }
    return normalizeSettings({ ...defaultSettings(), ...raw });
  }

  function saveDraft(s) {
    try {
      localStorage.setItem(storageKeyDraft(), JSON.stringify(normalizeSettings(s)));
    } catch {}
  }

  function hasDraft() {
    try {
      return localStorage.getItem(storageKeyDraft()) != null;
    } catch {
      return false;
    }
  }

  function clearDraft() {
    try {
      localStorage.removeItem(storageKeyDraft());
    } catch {}
  }

  // ============================================================
  // 3) Page hooks (Server = DB or Default)  ★event page専用
  // ============================================================
  function getPageHooks() {
    return document.getElementById("page-hooks");
  }

  function isEventPage() {
    const h = getPageHooks();
    const eid = (h?.dataset?.eventId || "").trim();
    return !!eid;
  }

  function getEventIdFromPage() {
    const h = getPageHooks();
    const eid = (h?.dataset?.eventId || "").trim();
    if (eid) return eid;

    const table = document.getElementById("participants-table");
    return ((table?.dataset?.eventId || "").trim()) || "";
  }

  function getEventSettingsFromServer() {
    const hooks = getPageHooks();
    if (!hooks) return null;

    const src = (hooks.dataset.displaySettingsSource || "").trim();
    if (src !== "db" && src !== "default") return null;

    const raw =
      (hooks.getAttribute("data-display-settings") || "").trim() ||
      (hooks.dataset.displaySettings || "").trim();

    const obj = safeJsonParse(raw, null);
    if (!obj) return null;

    return normalizeSettings(obj);
  }

  function getSaveUrlFromServer() {
    const hooks = getPageHooks();
    return (hooks?.dataset?.saveDisplaySettingsUrl || "").trim() || "";
  }

  function getSaveUrlFromModalFallback() {
    const modal = document.getElementById("display-settings-modal");
    return (modal?.dataset?.saveDisplaySettingsUrl || "").trim() || "";
  }

  // club-event-modal の hidden event_id（編集時に使うが、★このJSでは保存しない）
  function getClubEventModalEventId() {
    const el = document.getElementById("club-event-event-id");
    return (el?.value || "").trim();
  }

  function getClubEventSettingsFromHidden() {
    const clubModal = document.getElementById("club-event-modal");
    if (!clubModal) return null;

    const form = clubModal.querySelector("form");
    if (!form) return null;

    const hidden =
      form.querySelector("#club-event-display-settings") ||
      form.querySelector('input[name="display_settings_json"]');

    const raw = (hidden?.value || "").trim();
    if (!raw) return null;

    const obj = safeJsonParse(raw, null);
    return obj ? normalizeSettings(obj) : null;
  }

  // CSRF
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  // ★DB保存は event page 専用。club_event からは絶対呼ばない。
  async function saveEventSettingsFromEventPage(settings, eventId) {
    if (!isEventPage()) return { ok: false, reason: "not_event_page" };

    const url = getSaveUrlFromServer() || getSaveUrlFromModalFallback();
    const eid = (eventId || "").trim() || getEventIdFromPage();
    if (!url || !eid) return { ok: false, reason: "no_url_or_event" };

    const csrftoken = getCookie("csrftoken");
    const fd = new FormData();
    fd.append("event_id", eid);
    fd.append("settings_json", JSON.stringify(normalizeSettings(settings)));

    try {
      const r = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: csrftoken ? { "X-CSRFToken": csrftoken } : {},
        body: fd,
      });

      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) throw new Error(data.error || "not ok");

      const serverSettings = normalizeSettings(data.settings || {});
      return { ok: true, data, settings: serverSettings };
    } catch (err) {
      console.error(err);
      return { ok: false, reason: "network_or_server" };
    }
  }

  // ============================================================
  // 4) Apply helpers（DOMへ反映）
  // ============================================================
  function setHidden(el, hidden) {
    if (!el) return;
    el.style.display = hidden ? "none" : "";
  }

  function applyFlagColumnsVisibility(scope /* "common" | "event" */, show) {
    const table = document.getElementById("participants-table");
    if (!table) return;

    const allFlagThs = Array.from(table.querySelectorAll("thead th.flag-header"));
    if (allFlagThs.length === 0) return;

    const targetThs = allFlagThs.filter((th) => {
      const isEvent = th.classList.contains("event-flag-header");
      return scope === "event" ? isEvent : !isEvent;
    });
    if (targetThs.length === 0) return;

    const idxs = targetThs.map((th) => th.cellIndex).filter((i) => typeof i === "number");

    const theadRow = table.querySelector("thead tr");
    if (theadRow) {
      const cells = Array.from(theadRow.children);
      idxs.forEach((idx) => {
        const cell = cells[idx];
        if (cell) cell.style.display = show ? "" : "none";
      });
    }

    Array.from(table.querySelectorAll("tbody tr")).forEach((tr) => {
      const cells = Array.from(tr.children);
      idxs.forEach((idx) => {
        const cell = cells[idx];
        if (cell) cell.style.display = show ? "" : "none";
      });
    });

    const colgroup = table.querySelector("colgroup");
    if (colgroup) {
      const cols = Array.from(colgroup.children);
      idxs.forEach((idx) => {
        const col = cols[idx];
        if (col) col.style.display = show ? "" : "none";
      });
    }
  }

  function applyClassVisibility(show) {
    const table = document.getElementById("participants-table");
    if (!table) return;

    table.querySelectorAll('[data-ds="class"]').forEach((el) => {
      setHidden(el, !show);
    });

    const colgroup = table.querySelector("colgroup");
    if (colgroup) {
      colgroup.querySelectorAll('col[data-ds="class"]').forEach((col) => {
        setHidden(col, !show);
      });
    }
  }

  function applyScheduleVisibility(show) {
    setHidden(document.getElementById("schedule-area"), !show);

    document.querySelectorAll("h3").forEach((h3) => {
      const t = (h3.textContent || "").trim();
      if (t === "対戦表" || t.startsWith("対戦表（")) setHidden(h3, !show);
    });

    document.querySelectorAll(".match-settings-bar").forEach((bar) => {
      setHidden(bar, !show);
    });

    setHidden(document.getElementById("stats-area"), !show);

    const table = document.getElementById("participants-table");
    const isAdmin = (table?.dataset?.isAdmin || "") === "1";
    if (isAdmin && table) {
      table.querySelectorAll("td.match-cell").forEach((td) => setHidden(td, !show));

      const ths = Array.from(table.querySelectorAll("thead th"));
      const matchTh = ths.find((th) => (th.textContent || "").trim() === "試合参加");
      if (matchTh) setHidden(matchTh, !show);

      if (matchTh) {
        const idx = matchTh.cellIndex;
        const colgroup = table.querySelector("colgroup");
        const cols = colgroup ? Array.from(colgroup.children) : [];
        setHidden(cols[idx], !show);
      }
    }
  }

  function applyAll(settings) {
    const s = normalizeSettings(settings);
    applyFlagColumnsVisibility("common", !!s.common_flags);
    applyFlagColumnsVisibility("event", !!s.event_flags);
    applyClassVisibility(!!s.class);
    applyScheduleVisibility(!!s.schedule);
  }

  window.TennisDisplaySettings = window.TennisDisplaySettings || {};
  window.TennisDisplaySettings.applyAll = applyAll;

  // ============================================================
  // 5) Modal wiring
  // ============================================================
  function wireDisplaySettingsModal() {
    const modal = document.getElementById("display-settings-modal");
    const closeBtn = document.getElementById("close-display-settings-modal");
    const okBtn = document.getElementById("display-settings-ok");
    if (!modal || !closeBtn || !okBtn) return null;

    const content = modal.querySelector(".modal-content");
    if (!content) return null;

    // ★重要：OKボタンがsubmit扱いになって form を反応させるのをJSで物理遮断
    try {
      okBtn.setAttribute("type", "button");
    } catch {}

    // 多重配線阻止
    if (modal.dataset.wired === "1") return null;
    modal.dataset.wired = "1";

    function resetOpenState() {
      modal.dataset.opener = "";          // "club_event" | "event_page"
      modal.dataset.suppressReturn = "0";
      modal.dataset.openSnapshot = "";
      if (modal.dataset.returnOpener == null) modal.dataset.returnOpener = "";
      if (modal.dataset.returnKey == null) modal.dataset.returnKey = "";
    }
    resetOpenState();

    function isOpen() {
      return modal.classList.contains("is-open");
    }

    function openModal() {
      modal.style.zIndex = "3500";
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    }

    function reopenClubEventModalSoft() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;
      if (clubModal.classList.contains("is-open")) return;

      clubModal.classList.add("is-open");
      clubModal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
    }

    function closeModal() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      modal.style.zIndex = "";

      const opener = (modal.dataset.opener || "").trim();
      const suppress = (modal.dataset.suppressReturn || "0") === "1";
      if (!suppress && opener === "club_event") {
        reopenClubEventModalSoft();
      }

      resetOpenState();
    }

    function closeClubEventModalIfOpen() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;
      if (!clubModal.classList.contains("is-open")) return;

      clubModal.setAttribute("aria-hidden", "true");
      clubModal.classList.remove("is-open");
    }

    function writeDisplaySettingsToClubEventHidden(nextSettings) {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;

      const form = clubModal.querySelector("form");
      if (!form) return;

      let hidden =
        form.querySelector("#club-event-display-settings") ||
        form.querySelector('input[name="display_settings_json"]');

      if (!hidden) {
        hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.id = "club-event-display-settings";
        hidden.name = "display_settings_json";
        form.appendChild(hidden);
      }

      try {
        hidden.value = JSON.stringify(normalizeSettings(nextSettings));
      } catch {
        hidden.value = "";
      }

      // ★重要：相手JSの dirty 判定を確実に起動させる
      try {
        hidden.dispatchEvent(new Event("input", { bubbles: true }));
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
        form.dispatchEvent(new Event("input", { bubbles: true }));
        form.dispatchEvent(new Event("change", { bubbles: true }));
      } catch {}
    }


    // ★更新ボタンを「確実に」有効化（潰されにくいよう2段階）
    function markClubEventModalDirty() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;

      const form = clubModal.querySelector("form") || clubModal;

      // ① 自前フラグ（こちらの都合）
      clubModal.dataset.displaySettingsDirty = "1";
      if (form && form !== clubModal) form.dataset.dirty = "1";

      // ② “更新/保存” ボタンの探索を強化（id/属性/テキストまで見る）
      function findUpdateButtons() {
        const buttons = Array.from(clubModal.querySelectorAll("button, input[type='submit']"));
        return buttons.filter((el) => {
          const tag = (el.tagName || "").toLowerCase();
          const txt =
            tag === "input" ? (el.value || "") : (el.textContent || "");
          const t = (txt || "").replace(/\s+/g, "").trim();

          const id = (el.id || "").toLowerCase();
          const name = (el.getAttribute("name") || "").toLowerCase();
          const action = (el.getAttribute("data-action") || "").toLowerCase();
          const aria = (el.getAttribute("aria-label") || "").toLowerCase();
          const cls = (el.className || "").toLowerCase();

          // よくあるパターン全部拾う
          if (id.includes("update") || id.includes("save")) return true;
          if (name === "update" || name === "save") return true;
          if (action.includes("update") || action.includes("save")) return true;
          if (aria.includes("更新") || aria.includes("保存")) return true;
          if (cls.includes("update") || cls.includes("save")) return true;
          if (t === "更新" || t === "保存" || t.includes("更新") || t.includes("保存")) return true;

          return false;
        });
      }

      // ③ enable を“確実に”通す（直後に他JSに戻されることがあるので2段階）
      function forceEnable() {
        const btns = findUpdateButtons();
        btns.forEach((btn) => {
          try {
            btn.disabled = false;
            btn.removeAttribute("disabled");
            btn.classList.remove("pill-disabled");
            btn.classList.add("is-active");
            btn.setAttribute("aria-disabled", "false");
            // input[type=submit] の場合
            if (btn.tagName.toLowerCase() === "input") {
              btn.style.pointerEvents = "";
            }
          } catch {}
        });
      }

      forceEnable();
      setTimeout(forceEnable, 0);
      setTimeout(forceEnable, 50);

      // ★ここは絶対に自動保存トリガにしない（裏更新の元になる）
      // document.dispatchEvent(new CustomEvent("displaySettingsChanged"));
    }


    function getToggleByKey(key) {
      return modal.querySelector(`.ds-toggle[data-key="${key}"]`);
    }

    function setToggle(btn, on) {
      if (!btn) return;
      btn.classList.toggle("is-on", !!on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", !!on);
        icon.classList.toggle("check-off", !on);
        icon.textContent = "✓";
      }
    }

    function readToggle(btn) {
      return !!btn?.classList.contains("is-on");
    }

    function applySettingsToUI(s) {
      const m = normalizeSettings(s);
      setToggle(getToggleByKey("common_flags"), m.common_flags);
      setToggle(getToggleByKey("event_flags"), m.event_flags);
      setToggle(getToggleByKey("class"), m.class);
      setToggle(getToggleByKey("schedule"), m.schedule);
    }

    function getSettingsFromUI() {
      return normalizeSettings({
        common_flags: readToggle(getToggleByKey("common_flags")),
        event_flags: readToggle(getToggleByKey("event_flags")),
        class: readToggle(getToggleByKey("class")),
        schedule: readToggle(getToggleByKey("schedule")),
      });
    }

    function snapshotAtOpen(s) {
      try {
        modal.dataset.openSnapshot = JSON.stringify(normalizeSettings(s));
      } catch {
        modal.dataset.openSnapshot = "";
      }
    }

    function getSnapshotAtOpen() {
      const raw = (modal.dataset.openSnapshot || "").trim();
      return safeJsonParse(raw, null);
    }

    // close handlers
    closeBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation?.();
      closeModal();
    });

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    content.addEventListener("click", (e) => e.stopPropagation());

    // 固有フラグ編集
    modal.addEventListener(
      "click",
      (e) => {
        const editBtn = e.target.closest(".js-open-event-flag-menu");
        if (!editBtn) return;

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();

        window.__suppressMetaBarClickUntil = Date.now() + 400;

        modal.dataset.returnOpener = (modal.dataset.opener || "").trim();
        modal.dataset.suppressReturn = "1";
        closeModal();

        setTimeout(() => {
          document.dispatchEvent(new CustomEvent("openEventFlagMenu"));
        }, 0)
      },
      true
    );

    // Toggle click
    modal.addEventListener(
      "click",
      (e) => {
        const toggleBtn = e.target.closest(".ds-toggle[data-key]");
        const row = e.target.closest(".ds-row");
        if (!toggleBtn && !row) return;
        if (e.target.closest(".js-open-event-flag-menu")) return;

        const btn = toggleBtn || row.querySelector(".ds-toggle[data-key]");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        const nextOn = !readToggle(btn);
        setToggle(btn, nextOn);
      },
      true
    );

    // Esc
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!isOpen()) return;
      closeModal();
    });

    return {
      openModal,
      closeModal,
      applySettingsToUI,
      getSettingsFromUI,
      snapshotAtOpen,
      getSnapshotAtOpen,
      okBtn,
      closeClubEventModalIfOpen,
      markClubEventModalDirty,
      writeDisplaySettingsToClubEventHidden,
      setOpener: (ctx) => (modal.dataset.opener = ctx || ""),
      getOpener: () => (modal.dataset.opener || "").trim(),
      _modalEl: modal,
    };
  }

  // ============================================================
  // 6) Draft adoption: create -> first event page open
  // ============================================================
  async function adoptDraftOnceIfNeeded() {
    // ★event page 以外では何もしない
    if (!isEventPage()) return;

    const eid = getEventIdFromPage();
    if (!eid) return;
    if (!hasDraft()) return;

    // サーバが db/default を返しているなら “既にサーバ値がある” → draft破棄
    const serverNow = getEventSettingsFromServer();
    if (serverNow) {
      clearDraft();
      return;
    }

    // サーバ値が無いときだけ draft をDBへ移植（event page 専用保存関数）
    const draft = loadDraft();
    const saved = await saveEventSettingsFromEventPage(draft, eid);
    if (saved.ok) {
      clearDraft();
      applyAll(saved.settings || draft);
      return;
    }

    console.warn("[display_settings] adopt draft failed; keep draft for retry");
  }

  // ============================================================
  // 7) Open buttons（誤判定/二重登録を潰す）
  // ============================================================
  function initOpenButtons(wired) {
    if (window.__dsOpenButtonsWired) return;
    window.__dsOpenButtonsWired = true;

    function isClubEventModalOpen() {
      const m = document.getElementById("club-event-modal");
      if (!m) return false;

      if (m.classList.contains("is-open")) return true;

      const ah = (m.getAttribute("aria-hidden") || "").trim().toLowerCase();
      if (ah === "false" || ah === "") return true;

      return false;
    }

    document.addEventListener(
      "click",
      (e) => {
        const btn = e.target.closest(".js-open-display-settings");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();

        // ★文脈判定は opener ではなく “DOMの事実” のみ
        // event page なら常に event_page 扱い（DB値同期）
        const ctx = (isClubEventModalOpen() && !isEventPage())
          ? "club_event"
          : "event_page";

        if (ctx === "club_event") {
          const s = getClubEventSettingsFromHidden() || loadDraft();
          wired.setOpener("club_event");
          wired.applySettingsToUI(s);
          wired.snapshotAtOpen(s);
          wired.closeClubEventModalIfOpen?.();
          wired.openModal();
          return;
        }

        // event page：サーバ値のみ
        const serverS = getEventSettingsFromServer() || defaultSettings();
        wired.setOpener("event_page");
        wired.applySettingsToUI(serverS);
        wired.snapshotAtOpen(serverS);
        wired.openModal();
      },
      true
    );
  }

  // ============================================================
  // 8) OK button behavior（核心）
  // ============================================================
  function initOkButton(wired) {
    wired.okBtn.onclick = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation?.();

      const next = wired.getSettingsFromUI();

      // ★ここが最重要：DB保存は “event page の時だけ”
      if (isEventPage()) {
        const saved = await saveEventSettingsFromEventPage(next, getEventIdFromPage());
        if (saved.ok) {
          applyAll(saved.settings || next);
        }
        wired.closeModal();
        return;
      }

      // ★club_event：絶対にDB保存しない（fetch禁止）
      saveDraft(next);
      wired.writeDisplaySettingsToClubEventHidden?.(next);

      // ★無条件で更新ボタンを押せる状態にする（自動保存トリガは出さない）
      wired.markClubEventModalDirty?.();

      wired.closeModal();
    };
  }

  // ============================================================
  // 9) Reopen from Event Flag modal
  // ============================================================
  function initReopenHandler(wired) {
    document.addEventListener("reopenDisplaySettings", (ev) => {
      const detail = ev?.detail || {};
      const modalEl = wired._modalEl;

      const returnOpener = (modalEl?.dataset?.returnOpener || "").trim();
      const opener = returnOpener || (isEventPage() ? "event_page" : "club_event");

      let s = null;

      if (opener === "club_event") {
        s = getClubEventSettingsFromHidden() || loadDraft();
      } else {
        s = getEventSettingsFromServer() || defaultSettings();
      }

      if (typeof detail.forceEventFlags === "boolean") {
        s = { ...s, event_flags: detail.forceEventFlags };

        if (opener === "club_event") {
          saveDraft(s);
          wired.writeDisplaySettingsToClubEventHidden?.(s);
          wired.markClubEventModalDirty?.();
        } else {
          applyAll(s);
        }
      }

      wired.setOpener(opener);
      wired.applySettingsToUI(s);
      if (opener === "event_page") applyAll(s);

      wired.snapshotAtOpen(s);

      if (modalEl) {
        modalEl.dataset.returnOpener = "";
        modalEl.dataset.returnKey = "";
      }

      wired.openModal();
    });
  }

  // ============================================================
  // 10) Boot
  // ============================================================
  document.addEventListener("DOMContentLoaded", async () => {
    const wired = wireDisplaySettingsModal();
    if (!wired) return;

    // event page initial apply：★サーバ値のみ
    const serverS = getEventSettingsFromServer();
    if (serverS) {
      applyAll(serverS);
    } else {
      const hooks = getPageHooks();
      if (hooks && (hooks.dataset.displaySettingsSource || "").trim()) {
        applyAll(defaultSettings());
      }
    }

    // create直後：draftを一度だけDBへ移植（event pageのみ）
    await adoptDraftOnceIfNeeded();

    initOpenButtons(wired);
    initOkButton(wired);
    initReopenHandler(wired);
  });
})();
