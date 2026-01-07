// tennis/static/tennis/display_settings.js
// ============================================================
// Display Settings (per-event, localStorage) - unified version
//
// - event page: key = tennis:display_settings:event:<event_id>
// - club-event-modal create/edit: if event_id exists -> event key, else draft key
// - first open event page after create: if no event settings yet, adopt draft once
//
// Controls (4):
// - common_flags : common flag columns only (th.flag-header NOT .event-flag-header)
// - event_flags  : event flag columns only   (th.event-flag-header)
// - class        : cells with [data-ds="class"]
// - schedule     : schedule blocks (and admin-only stats / match-settings)
//
// UI:
// - open buttons: class ".js-open-display-settings" (NO id required)
// - modal toggle buttons: ".ds-toggle[data-key]"
// - click handling: event delegation (robust)
//
// EXTRA:
// - When display settings modal closes, reopen club-event-modal (event edit) if it was the opener.
// - BUT: if close is triggered by event_flags edit flow, DO NOT reopen club-event-modal.
// - If settings changed and saved, mark event edit modal "dirty" (enable Update button).
//
// ★FIX (this patch):
// - "event_flags" checkbox/row does NOT open any edit modal anymore.
// - Event-flag edit modal is opened ONLY by the slim "編集" pill button.
// - After returning from event-flag add/delete to Display Settings:
//    - If Display Settings was originally opened from club-event-modal,
//      then OK(Save) returns to club-event-modal.
// ============================================================

(function () {
  // ----------------------------
  // Keys
  // ----------------------------
  function storageKeyEvent(eventId) {
    return `tennis:display_settings:event:${eventId}`;
  }
  function storageKeyDraft() {
    return `tennis:display_settings:draft:club_event_modal`;
  }

  // ----------------------------
  // Utils
  // ----------------------------
  function safeJsonParse(raw, fallback) {
    try {
      return raw ? JSON.parse(raw) : fallback;
    } catch {
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
        event_flags: obj.event_flags !== false,
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    const hasOldSimple = ("flags" in obj) || ("class" in obj) || ("schedule" in obj);
    if (hasOldSimple) {
      return {
        common_flags: obj.flags !== false,
        event_flags: true,
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    const hasOldShow = ("show_flags" in obj) || ("show_class" in obj) || ("show_schedule" in obj);
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

  function loadByKey(key) {
    const raw = safeJsonParse(localStorage.getItem(key), {});
    const merged = { ...defaultSettings(), ...raw };

    if ("flags" in raw && !("common_flags" in raw)) {
      merged.common_flags = raw.flags !== false;
    }

    return normalizeSettings(merged);
  }

  function saveByKey(key, s) {
    try {
      localStorage.setItem(key, JSON.stringify(normalizeSettings(s)));
    } catch {}
  }

  function hasKey(key) {
    try {
      return localStorage.getItem(key) != null;
    } catch {
      return false;
    }
  }

  function setHidden(el, hidden) {
    if (!el) return;
    el.style.display = hidden ? "none" : "";
  }

  function setCellHidden(cell, hidden) {
    if (!cell) return;
    cell.style.display = hidden ? "none" : "";
  }

  function shallowEqualSettings(a, b) {
    const x = normalizeSettings(a);
    const y = normalizeSettings(b);
    return (
      x.common_flags === y.common_flags &&
      x.event_flags === y.event_flags &&
      x.class === y.class &&
      x.schedule === y.schedule
    );
  }

  // ----------------------------
  // [A] Column visibility helpers
  // ----------------------------
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
      idxs.forEach((idx) => setCellHidden(cells[idx], !show));
    }

    Array.from(table.querySelectorAll("tbody tr")).forEach((tr) => {
      const cells = Array.from(tr.children);
      idxs.forEach((idx) => setCellHidden(cells[idx], !show));
    });

    const colgroup = table.querySelector("colgroup");
    if (colgroup) {
      const cols = Array.from(colgroup.children);
      idxs.forEach((idx) => setCellHidden(cols[idx], !show));
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
  window.TennisDisplaySettings.loadByKey = loadByKey;

  // ----------------------------
  // [B] Modal wiring
  // ----------------------------
  function wireDisplaySettingsModal() {
    const modal = document.getElementById("display-settings-modal");
    const closeBtn = document.getElementById("close-display-settings-modal");
    const okBtn = document.getElementById("display-settings-ok");
    if (!modal || !closeBtn || !okBtn) return null;

    const content = modal.querySelector(".modal-content");
    if (!content) return null;

    if (modal.dataset.wired === "1") return null;
    modal.dataset.wired = "1";

    // --- internal state (per open) ---
    function ensureReturnFields() {
      if (modal.dataset.returnOpener == null) modal.dataset.returnOpener = "";
      if (modal.dataset.returnKey == null) modal.dataset.returnKey = "";
    }

    function resetOpenState() {
      // ★通常の open/close 状態だけリセット
      modal.dataset.activeKey = "";
      modal.dataset.opener = ""; // "club_event" | "event_page"
      modal.dataset.suppressReturn = "0";
      modal.dataset.openSnapshot = "";

      // ★returnOpener/returnKey はここで消さない（固有フラグ導線で reopen するときに使う）
      ensureReturnFields();
    }

    ensureReturnFields();
    resetOpenState();

    function isOpen() {
      return modal.classList.contains("is-open");
    }

    function openModal() {
      modal.style.zIndex = "3500";
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      modal.style.zIndex = "";

      // close後：元が club-event-modal なら復帰（ただし suppressReturn=1 の場合は抑止）
      const opener = (modal.dataset.opener || "").trim();
      const suppress = (modal.dataset.suppressReturn || "0") === "1";
      if (!suppress && opener === "club_event") {
        reopenClubEventModal();
      }

      resetOpenState();
    }

    function reopenClubEventModal() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;

      if (clubModal.classList.contains("is-open")) return;

      const openBtn =
        document.querySelector(".js-open-club-event-modal") ||
        clubModal.querySelector('[data-action="open-club-event-modal"]');

      if (openBtn) {
        openBtn.click();
        return;
      }

      clubModal.classList.add("is-open");
      clubModal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
    }

    function closeClubEventModalIfOpen() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;
      if (!clubModal.classList.contains("is-open")) return;

      const closeBtn =
        clubModal.querySelector("#close-club-event-modal") ||
        clubModal.querySelector(".js-close-club-event-modal") ||
        clubModal.querySelector('[data-action="close-club-event-modal"]');

      if (closeBtn) {
        closeBtn.click();
        return;
      }

      clubModal.classList.remove("is-open");
      clubModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
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
    }

    function markClubEventModalDirty() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;

      const candidates = [
        "#club-event-update",
        "#club-event-save",
        "#club-event-submit",
        "#club-event-ok",
        "#club-event-modal-update",
        "#club-event-modal-save",
        'button[name="update"]',
        'button[data-action="update"]',
        'button[type="submit"]',
      ];

      let btn = null;
      for (const sel of candidates) {
        const el = clubModal.querySelector(sel);
        if (el) {
          btn = el;
          break;
        }
      }

      if (btn) {
        btn.disabled = false;
        btn.classList.remove("pill-disabled");
        btn.classList.add("is-active");
        btn.setAttribute("aria-disabled", "false");
      }

      clubModal.dataset.displaySettingsDirty = "1";
      document.dispatchEvent(new CustomEvent("displaySettingsChanged"));
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
      closeModal();
    });

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    content.addEventListener("click", (e) => e.stopPropagation());

    // ============================================================
    // ★FIX1: "編集" ピルだけで固有フラグ編集モーダルを開く
    // ============================================================
    modal.addEventListener(
      "click",
      (e) => {
        const editBtn = e.target.closest(".js-open-event-flag-menu");
        if (!editBtn) return;

        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();

        // ★戻り先（club_event / event_page）を保持してから、DisplaySettings を閉じる
        ensureReturnFields();
        modal.dataset.returnOpener = (modal.dataset.opener || "").trim();
        modal.dataset.returnKey = (modal.dataset.activeKey || "").trim();

        // ★club-event-modal への自動復帰は抑止（いまは edit flow 中）
        modal.dataset.suppressReturn = "1";
        closeModal();

        document.dispatchEvent(new CustomEvent("openEventFlagMenu"));
      },
      true
    );

    // ============================================================
    // ★FIX2: トグルは「表示ON/OFF」だけ（event_flags も含めて全部同じ）
    //  - ここでは編集モーダルを開かない
    // ============================================================
    modal.addEventListener(
      "click",
      (e) => {
        const toggleBtn = e.target.closest(".ds-toggle[data-key]");
        const row = e.target.closest(".ds-row");
        if (!toggleBtn && !row) return;

        // 「編集」ピルは上のFIX1で処理するので、ここでは触らない
        if (e.target.closest(".js-open-event-flag-menu")) return;

        const btn = toggleBtn || row.querySelector(".ds-toggle[data-key]");
        if (!btn) return;

        const key = (btn.dataset.key || "").trim();
        if (!key) return;

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
      okBtn,
      closeClubEventModalIfOpen,
      markClubEventModalDirty,
      writeDisplaySettingsToClubEventHidden,
      snapshotAtOpen,
      getSnapshotAtOpen,
      setActiveContext: (ctx) => (modal.dataset.opener = ctx || ""),
      setActiveKey: (key) => (modal.dataset.activeKey = key || ""),
      setSuppressReturn: (v) => (modal.dataset.suppressReturn = v ? "1" : "0"),
      getActiveKey: () => (modal.dataset.activeKey || "").trim(),
      getOpener: () => (modal.dataset.opener || "").trim(),
    };
  }

  // ----------------------------
  // [C] Context key resolvers
  // ----------------------------
  function getEventIdFromPage() {
    const table = document.getElementById("participants-table");
    const eid = (table?.dataset?.eventId || "").trim();
    return eid || "";
  }

  function getKeyForEventPage() {
    const eid = getEventIdFromPage();
    return eid ? storageKeyEvent(eid) : "";
  }

  function getKeyForClubEventModal() {
    const hiddenEventId = document.getElementById("club-event-event-id");
    const eid = (hiddenEventId?.value || "").trim();
    return eid ? storageKeyEvent(eid) : storageKeyDraft();
  }

  // ----------------------------
  // [D] Adopt draft -> event (once)
  // ----------------------------
  function adoptDraftOnceIfNeeded() {
    const eventKey = getKeyForEventPage();
    if (!eventKey) return;

    const draftKey = storageKeyDraft();
    if (!hasKey(eventKey) && hasKey(draftKey)) {
      const draft = loadByKey(draftKey);
      saveByKey(eventKey, draft);
      try {
        localStorage.removeItem(draftKey);
      } catch {}
    }
  }

  // ----------------------------
  // [E] Open buttons: event delegation
  // ----------------------------
  function initOpenButtons(wired) {
    document.addEventListener(
      "click",
      (e) => {
        const btn = e.target.closest(".js-open-display-settings");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        const inClubEventModal = !!btn.closest("#club-event-modal");
        const key = inClubEventModal ? getKeyForClubEventModal() : getKeyForEventPage();
        if (!key) return;

        const s = loadByKey(key);
        wired.applySettingsToUI(s);

        wired.setActiveKey(key);
        wired.setActiveContext(inClubEventModal ? "club_event" : "event_page");
        wired.setSuppressReturn(false);
        wired.snapshotAtOpen(s);

        // 表示設定を開く前にイベント編集モーダルが開いていたなら閉じる
        if (inClubEventModal) wired.closeClubEventModalIfOpen?.();

        wired.openModal();
      },
      true
    );
  }

  // ----------------------------
  // [F] OK button: save to active key
  // ----------------------------
  function initOkButton(wired) {
    wired.okBtn.addEventListener("click", (e) => {
      e.preventDefault();

      const key = wired.getActiveKey();
      if (!key) return;

      const next = wired.getSettingsFromUI();
      const prev = wired.getSnapshotAtOpen();

      saveByKey(key, next);

      const opener = wired.getOpener();

      if (opener === "club_event") {
        wired.writeDisplaySettingsToClubEventHidden?.(next);
      }

      // eventページから開いた場合だけ「保存後に即反映」
      if (opener === "event_page") {
        applyAll(next);
      }

      // club-event-modal から開いた場合は即反映しない（dirtyだけ）
      if (opener === "club_event" && prev && !shallowEqualSettings(prev, next)) {
        wired.markClubEventModalDirty?.();
      }

      wired.closeModal();
    });
  }

  // ----------------------------
  // Boot
  // ----------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const wired = wireDisplaySettingsModal();
    if (!wired) return;

    adoptDraftOnceIfNeeded();

    const eventKey = getKeyForEventPage();
    if (eventKey) {
      applyAll(loadByKey(eventKey));
    }

    initOpenButtons(wired);
    initOkButton(wired);

    // ★固有フラグ側から「表示設定を開き直して」の要求を受ける
    // - 直前に Display Settings が club_event から開かれていたなら、その文脈に戻す
    document.addEventListener("reopenDisplaySettings", (ev) => {
      const detail = ev?.detail || {};

      const modalEl = document.getElementById("display-settings-modal");
      const returnOpener = (modalEl?.dataset?.returnOpener || "").trim();

      // ★戻り先があれば優先。なければ event_page
      const opener = returnOpener || "event_page";

      // ★key は opener に合わせる（club_event なら draft/event どちらも対応）
      const key = opener === "club_event" ? getKeyForClubEventModal() : getKeyForEventPage();
      if (!key) return;

      const s = loadByKey(key);

      if (typeof detail.forceEventFlags === "boolean") {
        s.event_flags = detail.forceEventFlags;
        saveByKey(key, s);
      }

      wired.applySettingsToUI(s);

      // ★event_page のときだけ即反映（従来通り）
      if (opener === "event_page") {
        applyAll(s);
      }

      wired.setActiveKey(key);
      wired.setActiveContext(opener);
      wired.setSuppressReturn(false);
      wired.snapshotAtOpen(s);

      // ★使い終わったらクリア（次回に持ち越さない）
      if (modalEl) {
        modalEl.dataset.returnOpener = "";
        modalEl.dataset.returnKey = "";
      }

      wired.openModal();
    });
  });
})();
