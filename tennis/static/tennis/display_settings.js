// tennis/static/tennis/display_settings.js
// ============================================================
// Display Settings (Single Source of Truth / 大掃除版・最終)
//
// 方針（このファイルが唯一の制御点）
// ------------------------------------------------------------
// ✅ event page：DBが唯一の正（localStorageは絶対に参照しない）
//   - load : #page-hooks[data-display-settings] を読む（db/defaultどちらもサーバ値）
//   - save : POST to #page-hooks[data-save-display-settings-url]（DB保存）
//   - apply: 常にサーバ値で描画（別端末でも一致）
//
// ✅ club-event-modal（イベント作成/編集モーダル）
//   - ★新規作成（mode=create）では「表示設定」機能を完全に無効化（ボタン非表示・開かない）
//   - 既存編集（mode=edit）では、hidden(display_settings_json) を “下書き” として使う（localStorage禁止）
//   - このJSではDB保存しない（裏更新しない）
//     → DB反映は「イベント編集モーダルの更新ボタン」だけ
//
// 大掃除のポイント
// ------------------------------------------------------------
// - クリック配線は「documentの1本」だけ（多重登録防止）
// - OKボタンは onclick を上書き（他JSのaddEventListenerを潰す）
// - “固有フラグ設定” への遷移/復帰は CustomEvent だけで統一
// - event page で localStorage を読む道を完全封鎖
// - ★createの表示設定を根絶（draft/adopt/LSは削除）
// ============================================================

(function () {
  "use strict";

  // ============================================================
  // 0) Const
  // ============================================================
  const Z_MODAL = "3500";
  const SUPPRESS_MS = 450; // メタバー等の誤クリック抑止の猶予

  // ============================================================
  // 1) Utils
  // ============================================================
  function safeJsonParse(raw, fallback) {
    if (!raw) return fallback;

    try {
      return JSON.parse(raw);
    } catch {}

    // escapejs / HTML escape 混入対策
    try {
      let fixed = String(raw);
      fixed = fixed.replace(/\\u0022/g, '"');
      fixed = fixed.replace(/&quot;/g, '"');
      fixed = fixed.replace(/&amp;quot;/g, '"');
      return JSON.parse(fixed);
    } catch {
      console.warn("[DS] JSON parse failed", { raw });
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

  // 互換：旧キーも受け入れて新キーへ正規化
  function normalizeSettings(obj) {
    const d = defaultSettings();
    if (!obj || typeof obj !== "object") return d;

    const hasNew =
      "common_flags" in obj || "event_flags" in obj || "class" in obj || "schedule" in obj;
    if (hasNew) {
      return {
        common_flags: obj.common_flags !== false,
        event_flags: obj.event_flags === true, // default=false → trueのみtrue
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    const hasOldSimple = "flags" in obj || "class" in obj || "schedule" in obj;
    if (hasOldSimple) {
      return {
        common_flags: obj.flags !== false,
        event_flags: true, // 旧には無い → ON寄せ
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    const hasOldShow = "show_flags" in obj || "show_class" in obj || "show_schedule" in obj;
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

  function nowMs() {
    return Date.now();
  }

  // ============================================================
  // 2) Page hooks (Server = DB or Default)  ★event page専用
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

  // club-event-modal の hidden display_settings_json（edit専用で使う）
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

  // club-event-modal: mode 判定
  function getClubEventMode() {
    const m = document.getElementById("club-event-mode");
    return ((m?.value || "").trim().toLowerCase()) || "";
  }

  function getClubEventEventId() {
    const el = document.getElementById("club-event-event-id");
    return ((el?.value || "").trim()) || "";
  }

  function isClubEventModalOpen() {
    const m = document.getElementById("club-event-modal");
    if (!m) return false;
    if (m.classList.contains("is-open")) return true;

    const ah = (m.getAttribute("aria-hidden") || "").trim().toLowerCase();
    if (ah === "false" || ah === "") return true;

    return false;
  }

  // ★club-event-modal の「表示設定」は edit だけ許可
  function isClubEventEditContext() {
    if (!isClubEventModalOpen()) return false;
    if (isEventPage()) return false; // event page上なら club_event と見なさない
    const mode = getClubEventMode();
    if (mode !== "edit") return false;
    const eid = getClubEventEventId();
    return !!eid;
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
      return { ok: true, settings: serverSettings, data };
    } catch (err) {
      console.error("[DS] save failed", err);
      return { ok: false, reason: "network_or_server" };
    }
  }

  // ============================================================
  // 3) Apply helpers（DOMへ反映）
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

    const idxs = targetThs
      .map((th) => th.cellIndex)
      .filter((i) => typeof i === "number");

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

  // 他JSから使う場合に備えた最小公開（ただし保存はここに寄せる）
  window.TennisDisplaySettings = window.TennisDisplaySettings || {};
  window.TennisDisplaySettings.applyAll = applyAll;

  // ============================================================
  // 4) club-event-modal：表示設定ボタンを create で消す（根絶）
  // ============================================================
  function syncClubEventDisplaySettingsButtons() {
    const root = document.getElementById("club-event-modal");
    if (!root) return;

    const btns = Array.from(root.querySelectorAll(".js-open-display-settings"));
    if (!btns.length) return;

    const mode = getClubEventMode();
    const eid = getClubEventEventId();

    // create は完全禁止（表示しない）
    const allow = mode === "edit" && !!eid;

    btns.forEach((b) => {
      // “data-show-on-edit-only=1” があればそれを尊重（無ければ従来ボタンも同様に処理）
      const editOnly = (b.dataset?.showOnEditOnly || "") === "1";
      if (editOnly || true) {
        b.style.display = allow ? "" : "none";
        b.setAttribute("aria-hidden", allow ? "false" : "true");
      }
    });
  }

  function wireClubEventModeObserver() {
    const root = document.getElementById("club-event-modal");
    if (!root) return;
    if (root.dataset.dsModeObserved === "1") return;
    root.dataset.dsModeObserved = "1";

    const modeEl = document.getElementById("club-event-mode");
    const idEl = document.getElementById("club-event-event-id");

    // input/change で拾う
    modeEl?.addEventListener("input", syncClubEventDisplaySettingsButtons);
    modeEl?.addEventListener("change", syncClubEventDisplaySettingsButtons);
    idEl?.addEventListener("input", syncClubEventDisplaySettingsButtons);
    idEl?.addEventListener("change", syncClubEventDisplaySettingsButtons);

    // class is-open の変化も拾う（calendar.js の open/close を追随）
    try {
      const mo = new MutationObserver(() => syncClubEventDisplaySettingsButtons());
      mo.observe(root, { attributes: true, attributeFilter: ["class", "aria-hidden"] });
    } catch {}

    // 初回
    syncClubEventDisplaySettingsButtons();
  }

  // ============================================================
  // 5) Modal wiring（ここだけで open/close/OK を完結）
  // ============================================================
  function wireDisplaySettingsModal() {
    const modal = document.getElementById("display-settings-modal");
    const closeBtn = document.getElementById("close-display-settings-modal");
    const okBtn = document.getElementById("display-settings-ok");
    if (!modal || !closeBtn || !okBtn) return null;

    const content = modal.querySelector(".modal-content");
    if (!content) return null;

    // ★OKがsubmit扱いでformが暴れるのを封鎖
    try {
      okBtn.setAttribute("type", "button");
    } catch {}

    // 多重配線阻止（このファイルの再読み込み/遅延読み込み対策）
    if (modal.dataset.dsWired === "1") return null;
    modal.dataset.dsWired = "1";

    function resetOpenState() {
      modal.dataset.opener = ""; // "club_event" | "event_page"
      modal.dataset.suppressReturn = "0";
      modal.dataset.openSnapshot = "";
      modal.dataset.returnOpener = modal.dataset.returnOpener || "";
    }
    resetOpenState();

    function isOpen() {
      return modal.classList.contains("is-open");
    }

    function openModal() {
      modal.style.zIndex = Z_MODAL;
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

      // dirty 判定を確実に起動
      try {
        hidden.dispatchEvent(new Event("input", { bubbles: true }));
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
        form.dispatchEvent(new Event("input", { bubbles: true }));
        form.dispatchEvent(new Event("change", { bubbles: true }));
      } catch {}
    }

    // club-event の更新ボタンを「押せる状態」にする（自動保存トリガは絶対に出さない）
    function markClubEventModalDirty() {
      const clubModal = document.getElementById("club-event-modal");
      if (!clubModal) return;

      const form = clubModal.querySelector("form") || clubModal;

      clubModal.dataset.displaySettingsDirty = "1";
      if (form && form !== clubModal) form.dataset.dirty = "1";

      function findUpdateButtons() {
        const buttons = Array.from(clubModal.querySelectorAll("button, input[type='submit']"));
        return buttons.filter((el) => {
          const tag = (el.tagName || "").toLowerCase();
          const txt = tag === "input" ? (el.value || "") : (el.textContent || "");
          const t = (txt || "").replace(/\s+/g, "").trim();

          const id = (el.id || "").toLowerCase();
          const name = (el.getAttribute("name") || "").toLowerCase();
          const action = (el.getAttribute("data-action") || "").toLowerCase();
          const aria = (el.getAttribute("aria-label") || "").toLowerCase();
          const cls = (el.className || "").toLowerCase();

          if (id.includes("update") || id.includes("save")) return true;
          if (name === "update" || name === "save") return true;
          if (action.includes("update") || action.includes("save")) return true;
          if (aria.includes("更新") || aria.includes("保存")) return true;
          if (cls.includes("update") || cls.includes("save")) return true;
          if (t === "更新" || t === "保存" || t.includes("更新") || t.includes("保存")) return true;

          return false;
        });
      }

      function forceEnable() {
        const btns = findUpdateButtons();
        btns.forEach((btn) => {
          try {
            btn.disabled = false;
            btn.removeAttribute("disabled");
            btn.classList.remove("pill-disabled");
            btn.classList.add("is-active");
            btn.setAttribute("aria-disabled", "false");
            if (btn.tagName.toLowerCase() === "input") {
              btn.style.pointerEvents = "";
            }
          } catch {}
        });
      }

      forceEnable();
      setTimeout(forceEnable, 0);
      setTimeout(forceEnable, 50);
    }

    // ----------------------------
    // Toggle helpers
    // ----------------------------
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

    // ----------------------------
    // Close handlers（ここだけ）
    // ----------------------------
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

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!isOpen()) return;
      closeModal();
    });

    // 固有フラグ編集（表示設定 → 固有フラグへ）
    // - “イベント編集モーダル” が後ろで開く問題は、ここでのクリックを強制遮断し、
    //   さらに meta bar 側のクリック抑止フラグを立てることで回避する。
    modal.addEventListener(
      "click",
      (e) => {
        const editBtn = e.target.closest(".js-open-event-flag-menu");
        if (!editBtn) return;

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();

        // 後ろのクリック連鎖を止めるための抑止フラグ（event.js 側で参照してもOK）
        window.__suppressMetaBarClickUntil = nowMs() + SUPPRESS_MS;

        modal.dataset.returnOpener = (modal.dataset.opener || "").trim();
        modal.dataset.suppressReturn = "1";
        closeModal();

        // 固有フラグモーダルを開く（ここだけ）
        setTimeout(() => {
          document.dispatchEvent(new CustomEvent("openEventFlagMenu"));
        }, 0);
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

    return {
      openModal,
      closeModal,
      isOpen,
      applySettingsToUI,
      getSettingsFromUI,
      snapshotAtOpen,
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
  // 6) Open buttons（documentに1本だけ）
  //    - club-event は edit のときだけ開ける（create根絶）
  // ============================================================
  function initOpenButtons(wired) {
    if (window.__dsOpenButtonsWired) return;
    window.__dsOpenButtonsWired = true;

    document.addEventListener(
      "click",
      (e) => {
        const btn = e.target.closest(".js-open-display-settings");
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();

        // club-event(create) は絶対に開かない（根絶）
        if (isClubEventModalOpen() && !isEventPage()) {
          if (!isClubEventEditContext()) {
            // 念のため：ボタンが見えてしまってもここで止める
            return;
          }

          // club-event(edit)：hidden を優先（無ければ default）
          const s = getClubEventSettingsFromHidden() || defaultSettings();
          wired.setOpener("club_event");
          wired.applySettingsToUI(s);
          wired.snapshotAtOpen(s);
          wired.closeClubEventModalIfOpen?.();
          wired.openModal();
          return;
        }

        // event page：サーバ値のみ（localStorage禁止）
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
  // 7) OK button behavior（核心）
  //    - event page はDB保存
  //    - club-event(edit) はhiddenへ保存 + dirty（DB保存しない）
  //    - club-event(create) は到達しない（open自体禁止）
  // ============================================================
  function initOkButton(wired) {
    // ★onclick上書きで “他JSのaddEventListener” を潰す（大掃除の要）
    wired.okBtn.onclick = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation?.();

      const next = wired.getSettingsFromUI();

      // event page：DB保存する
      if (isEventPage()) {
        const saved = await saveEventSettingsFromEventPage(next, getEventIdFromPage());
        if (saved.ok) applyAll(saved.settings || next);
        wired.closeModal();
        return;
      }

      // club_event：editのみ（createはopen自体禁止）
      if (!isClubEventEditContext()) {
        wired.closeModal();
        return;
      }

      // 絶対にDB保存しない（fetch禁止）
      wired.writeDisplaySettingsToClubEventHidden?.(next);
      wired.markClubEventModalDirty?.();
      wired.closeModal();
    };
  }

  // ============================================================
  // 8) Reopen from Event Flag modal（復帰はこれだけ）
  //    - create は opener にしない（根絶）
  // ============================================================
  function initReopenHandler(wired) {
    document.addEventListener("reopenDisplaySettings", (ev) => {
      const detail = ev?.detail || {};
      const modalEl = wired._modalEl;

      const returnOpener = (modalEl?.dataset?.returnOpener || "").trim();

      // opener 決定：
      // - 明示returnOpenerがあれば優先
      // - 無ければ event page なら event_page
      // - それ以外は club_event だが、edit 以外は許可しない
      let opener = returnOpener || (isEventPage() ? "event_page" : "club_event");
      if (opener === "club_event" && !isClubEventEditContext()) {
        // create/不正コンテキストなら event_page を優先（ただし event page でもなければ閉じる）
        if (!isEventPage()) return;
        opener = "event_page";
      }

      let s =
        opener === "club_event"
          ? (getClubEventSettingsFromHidden() || defaultSettings())
          : (getEventSettingsFromServer() || defaultSettings());

      // 固有フラグモーダルから event_flags を強制反映したい場合
      if (typeof detail.forceEventFlags === "boolean") {
        s = { ...s, event_flags: detail.forceEventFlags };

        if (opener === "club_event") {
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
      }

      wired.openModal();
    });
  }

  // ============================================================
  // 9) Boot
  // ============================================================
  document.addEventListener("DOMContentLoaded", async () => {
    const wired = wireDisplaySettingsModal();
    if (!wired) return;

    // event page initial apply：★サーバ値のみ
    const serverS = getEventSettingsFromServer();
    if (serverS) {
      applyAll(serverS);
    } else {
      // サーバが "source" を出してるのに settings が取れないときは default で描画
      const hooks = getPageHooks();
      if (hooks && (hooks.dataset.displaySettingsSource || "").trim()) {
        applyAll(defaultSettings());
      }
    }

    // club-event create の表示設定を根絶（ボタン表示制御）
    wireClubEventModeObserver();

    initOpenButtons(wired);
    initOkButton(wired);
    initReopenHandler(wired);
  });
})();
