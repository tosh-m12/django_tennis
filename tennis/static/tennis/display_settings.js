// tennis/static/tennis/display_settings.js
// ============================================================
// Display Settings (per-event, localStorage) - robust version
// - event page: key = tennis:display_settings:event:<event_id>
// - club-event-modal create: key = tennis:display_settings:draft:club_event_modal
// - first open event page after create: if no event settings yet, adopt draft once
//
// IMPORTANT:
// - open buttons use class ".js-open-display-settings" (NO id)
// - click handling uses event delegation (works with dynamic DOM)
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
    return { flags: true, class: true, schedule: true };
  }

  function loadByKey(key) {
    return { ...defaultSettings(), ...safeJsonParse(localStorage.getItem(key), {}) };
  }

  function saveByKey(key, s) {
    try {
      localStorage.setItem(key, JSON.stringify(s));
    } catch {}
  }

  function hasKey(key) {
    try {
      return localStorage.getItem(key) != null;
    } catch {
      return false;
    }
  }

  function setElHidden(el, hidden) {
    if (!el) return;
    el.style.display = hidden ? "none" : "";
  }

  // ----------------------------
  // [A] Flags visibility
  // ----------------------------
  function applyFlagsVisibility(show) {
    const table = document.getElementById("participants-table");
    if (!table) return;

    const flagThs = Array.from(table.querySelectorAll("thead th.flag-header"));
    if (flagThs.length === 0) return;

    const flagIndexes = flagThs
      .map((th) => th.cellIndex)
      .filter((i) => typeof i === "number");

    // thead
    const theadRow = table.querySelector("thead tr");
    if (theadRow) {
      const cells = Array.from(theadRow.children);
      flagIndexes.forEach((idx) => {
        const c = cells[idx];
        if (c) c.style.display = show ? "" : "none";
      });
    }

    // tbody
    Array.from(table.querySelectorAll("tbody tr")).forEach((tr) => {
      const cells = Array.from(tr.children);
      flagIndexes.forEach((idx) => {
        const c = cells[idx];
        if (c) c.style.display = show ? "" : "none";
      });
    });

    // colgroup
    const colgroup = table.querySelector("colgroup");
    if (colgroup) {
      const cols = Array.from(colgroup.children);
      flagIndexes.forEach((idx) => {
        const c = cols[idx];
        if (c) c.style.display = show ? "" : "none";
      });
    }
  }

  // ----------------------------
  // [B] Schedule visibility
  // ----------------------------
  function applyScheduleVisibility(show) {
    const scheduleArea = document.getElementById("schedule-area");
    setElHidden(scheduleArea, !show);

    // headings
    document.querySelectorAll("h3").forEach((h3) => {
      const t = (h3.textContent || "").trim();
      if (t === "対戦表" || t.startsWith("対戦表（")) {
        setElHidden(h3, !show);
      }
    });

    // admin bar
    document.querySelectorAll(".match-settings-bar").forEach((bar) => {
      setElHidden(bar, !show);
    });

    // admin stats
    const statsArea = document.getElementById("stats-area");
    setElHidden(statsArea, !show);

    // admin: match column
    const table = document.getElementById("participants-table");
    const isAdmin = (table?.dataset?.isAdmin || "") === "1";
    if (isAdmin && table) {
      table.querySelectorAll("td.match-cell").forEach((td) => {
        td.style.display = show ? "" : "none";
      });

      const ths = Array.from(table.querySelectorAll("thead th"));
      const matchTh = ths.find((th) => (th.textContent || "").trim() === "試合参加");
      if (matchTh) matchTh.style.display = show ? "" : "none";

      if (matchTh) {
        const idx = matchTh.cellIndex;
        const colgroup = table.querySelector("colgroup");
        const cols = colgroup ? Array.from(colgroup.children) : [];
        const col = cols[idx];
        if (col) col.style.display = show ? "" : "none";
      }
    }
  }

  function applyAll(settings) {
    applyFlagsVisibility(!!settings.flags);
    applyScheduleVisibility(!!settings.schedule);
    applyClassVisibility(!!settings.class);
  }

  // ----------------------------
  // [C] Class visibility
  // ----------------------------
  function applyClassVisibility(show) {
  const table = document.getElementById("participants-table");
  if (!table) return;

  // th/td を data-ds="class" で制御（テンプレ側で付ける）
  table.querySelectorAll('[data-ds="class"]').forEach((el) => {
      el.style.display = show ? "" : "none";
  });

  // （任意）colgroup に data-ds="class" を付けてる場合だけ効かせる
  const colgroup = table.querySelector("colgroup");
  if (colgroup) {
      colgroup.querySelectorAll('col[data-ds="class"]').forEach((col) => {
      col.style.display = show ? "" : "none";
      });
  }
  }


  // ----------------------------
  // [C] Display Settings Modal wiring (1 time)
  // ----------------------------
  function wireDisplaySettingsModal() {
    const modal = document.getElementById("display-settings-modal");
    const closeBtn = document.getElementById("close-display-settings-modal");
    const okBtn = document.getElementById("display-settings-ok");
    if (!modal || !closeBtn || !okBtn) return null;

    const content = modal.querySelector(".modal-content");
    const toggles = Array.from(modal.querySelectorAll(".ds-toggle"));
    if (!content || toggles.length === 0) return null;

    // modal open/close
    const openModal = () => {
      modal.style.zIndex = "3500";
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    };

    const closeModal = () => {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      modal.style.zIndex = "";
    };

    function setToggle(btn, on) {
      btn.classList.toggle("is-on", !!on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", !!on);
        icon.classList.toggle("check-off", !on);
      }
    }

    function getToggleState(btn) {
      return btn.classList.contains("is-on");
    }

    function applySettingsToUI(s) {
      const merged = { ...defaultSettings(), ...(s || {}) };
      toggles.forEach((btn) => {
        const key = (btn.dataset.key || "").trim();
        if (!key) return;
        setToggle(btn, !!merged[key]);
      });
    }

    function getSettingsFromUI() {
      const s = defaultSettings();
      toggles.forEach((btn) => {
        const key = (btn.dataset.key || "").trim();
        if (!key) return;
        s[key] = getToggleState(btn);
      });
      return s;
    }

    // close events
    closeBtn.addEventListener("click", (e) => {
      e.preventDefault();
      closeModal();
    });

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    content.addEventListener("click", (e) => e.stopPropagation());

    // toggle click (button + row)
    toggles.forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        setToggle(btn, !getToggleState(btn));
      });

      const row = btn.closest(".ds-row");
      if (row) {
        row.addEventListener("click", (e) => {
          if (e.target === btn || btn.contains(e.target)) return;
          e.preventDefault();
          setToggle(btn, !getToggleState(btn));
        });
      }
    });

    return {
      openModal,
      closeModal,
      applySettingsToUI,
      getSettingsFromUI,
      okBtn,
    };
  }

  // ----------------------------
  // [D] Context key resolvers
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
  // [E] Adopt draft -> event (once)
  // ----------------------------
  function adoptDraftOnceIfNeeded() {
    const eventKey = getKeyForEventPage();
    if (!eventKey) return;

    if (!hasKey(eventKey) && hasKey(storageKeyDraft())) {
      const draft = loadByKey(storageKeyDraft());
      saveByKey(eventKey, draft);
      try {
        localStorage.removeItem(storageKeyDraft());
      } catch {}
    }
  }

  // ----------------------------
  // [F] Open button: event delegation
  // ----------------------------
  function initOpenButtons(wired) {
    document.addEventListener(
      "click",
      (e) => {
        const btn = e.target.closest(".js-open-display-settings");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        // どの文脈から押されたか
        const inClubEventModal = !!btn.closest("#club-event-modal");

        const key = inClubEventModal ? getKeyForClubEventModal() : getKeyForEventPage();
        if (!key) return;

        const s = loadByKey(key);
        wired.applySettingsToUI(s);
        wired.openModal();

        // OKボタンは「今どのkeyに保存するか」を保持しておく
        wired.__activeStorageKey = key;
      },
      true
    );
  }

  // ----------------------------
  // [G] OK button: save to active key
  // ----------------------------
  function initOkButton(wired) {
    wired.okBtn.addEventListener("click", (e) => {
      e.preventDefault();

      const key = (wired.__activeStorageKey || "").trim();
      if (!key) return;

      const next = wired.getSettingsFromUI();
      saveByKey(key, next);

      // eventページなら即反映（クラブホーム側はDOMが無いので無害）
      applyAll(next);

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

    // eventページなら初期反映
    const eventKey = getKeyForEventPage();
    if (eventKey) {
      applyAll(loadByKey(eventKey));
    }

    initOpenButtons(wired);
    initOkButton(wired);
  });
})();
