// tennis/static/tennis/ui_modal.js
// ★完成版（固有フラグ：追加/削除の安定化 + 追加/削除後に表示設定へ戻す：ページリロード無し + 更新ボタンをアクティブ化）
//
// 目的：
// - 固有フラグ 追加/削除 API を JSON で送る（400回避）
// - admin_token は拾えるだけ拾う（環境差吸収）
// - クリック伝播事故で別モーダルが開くのを止める
// - ★追加/削除 成功後：ページリロードせずに Display Settings を再表示（event_flags を適切にON/OFF）
// - ★0個のまま閉じた場合：Display Settings を event_flags OFF で再表示（従来要件）
// - ★FIX：固有フラグの追加/削除が行われたら、イベント編集モーダルの更新ボタンをアクティブ化（dirty）
//
// 注意：display_settings.js は触らなくてOK（reopenDisplaySettings イベントを投げるだけ）

(function () {
  let autoCloseTimer = null;

  function showMessage(text, ms = 2200) {
    const msgModal = document.getElementById("ui-message-modal");
    const msgBody = document.getElementById("ui-message-body");
    if (!msgModal || !msgBody) return;

    if (autoCloseTimer) clearTimeout(autoCloseTimer);

    msgBody.textContent = text || "";
    msgModal.classList.add("is-open");
    msgModal.setAttribute("aria-hidden", "false");

    autoCloseTimer = setTimeout(() => {
      msgModal.classList.remove("is-open");
      msgModal.setAttribute("aria-hidden", "true");
    }, ms);
  }

  function confirm(message, opts = {}) {
    const modal = document.getElementById("ui-confirm-modal");
    const body = document.getElementById("ui-confirm-body");
    const btnOk = document.getElementById("ui-confirm-ok");
    if (!modal || !body || !btnOk) return;

    const okText = opts.okText || "OK";
    const onOk = opts.onOk;

    body.textContent = message || "";
    btnOk.textContent = okText;

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");

    function close() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      btnOk.removeEventListener("click", okHandler);
    }

    function okHandler() {
      close();
      if (typeof onOk === "function") onOk();
    }

    btnOk.addEventListener("click", okHandler);

    modal.addEventListener(
      "click",
      (e) => {
        if (e.target === modal) close();
      },
      { once: true }
    );
  }

  window.UI = window.UI || {};
  window.UI.showMessage = showMessage;
  window.UI.confirm = confirm;
})();

// ============================================================
// [COMMON] CSRF helpers（meta -> cookie）
// ============================================================
(function initCsrfHelpers() {
  window.UI = window.UI || {};
  if (window.UI.getCsrfToken) return;

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function getCsrfFromMeta() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return (meta?.getAttribute("content") || "").trim();
  }

  function getCsrfToken() {
    return getCsrfFromMeta() || getCookie("csrftoken") || "";
  }

  window.UI.getCsrfToken = getCsrfToken;
})();

// ============================================================
// [COMMON] helpers for modal interaction with Display Settings
// ============================================================
(function initModalBridgeHelpers() {
  function requestReopenDisplaySettings(detail) {
    document.dispatchEvent(
      new CustomEvent("reopenDisplaySettings", { detail: detail || {} })
    );
  }

  function stopAll(e) {
    try {
      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
    } catch {}
  }

  // ★admin_token を拾えるだけ拾う（ページ/hidden/モーダル）
  function pickAdminToken() {
    const hooks = document.getElementById("page-hooks");
    const t1 = (hooks?.dataset?.adminToken || "").trim();
    if (t1) return t1;

    const hidden =
      document.querySelector('input[name="admin_token"]') ||
      document.querySelector("#admin-token") ||
      document.querySelector("#club-admin-token");
    const t2 = (hidden?.value || "").trim();
    if (t2) return t2;

    const clubModal = document.getElementById("club-event-modal");
    const t3 = (clubModal?.dataset?.adminToken || "").trim();
    if (t3) return t3;

    const any = document.querySelector("[data-admin-token], [data-admintoken]");
    const t4 = (any?.dataset?.adminToken || any?.dataset?.admintoken || "").trim();
    if (t4) return t4;

    return "";
  }

  // ★FIX：イベント編集モーダルの更新ボタンをアクティブ化（固有フラグの追加/削除が行われたら必ず呼ぶ）
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
      if (el) { btn = el; break; }
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

  window.UI = window.UI || {};
  window.UI._requestReopenDisplaySettings = requestReopenDisplaySettings;
  window.UI._stopAll = stopAll;
  window.UI._pickAdminToken = pickAdminToken;
  window.UI._markClubEventModalDirty = markClubEventModalDirty;
})();

// ============================================================
// Event Flag Settings Modal (固有フラグ名の入力)
// ============================================================
(function initEventFlagSettingsModal() {
  const modal = document.getElementById("event-flag-settings-modal");
  if (!modal) return;
  if (modal.dataset.wired === "1") return;
  modal.dataset.wired = "1";

  const openBtns = document.querySelectorAll(".js-open-event-flag-settings");
  const closeBtn = document.getElementById("close-event-flag-settings-modal");
  const cancelBtn = document.getElementById("event-flag-settings-cancel");
  const addBtn = document.getElementById("event-flag-settings-add");

  const input = document.getElementById("event-flag-name-input");
  const hint = document.getElementById("event-flag-hint");

  const MAX_EVENT_FLAGS = 2;

  function isOpen() { return modal.classList.contains("is-open"); }
  function open() { modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); }
  function close() { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }

  function getEventIdForSave() {
    const el = document.getElementById("club-event-event-id");
    const v = (el?.value || "").trim();
    if (v) return v;

    const hooks = document.getElementById("page-hooks");
    const v2 = (hooks?.dataset?.eventId || "").trim();
    if (v2) return v2;

    return "";
  }

  function getExistingEventFlagsCount() {
    const ths = document.querySelectorAll("th.event-flag-header");
    if (ths && ths.length) return ths.length;

    const hooks = document.getElementById("page-hooks");
    const c = (hooks?.dataset?.eventFlagsCount || "").trim();
    if (c && /^\d+$/.test(c)) return parseInt(c, 10);

    return 0;
  }

  function disableAdd(reasonText) {
    if (input) input.disabled = true;
    if (addBtn) {
      addBtn.disabled = true;
      addBtn.classList.add("pill-disabled");
      addBtn.setAttribute("aria-disabled", "true");
    }
    if (hint && reasonText) hint.textContent = reasonText;
  }

  function enableAdd() {
    if (input) input.disabled = false;
    if (addBtn) {
      addBtn.disabled = false;
      addBtn.classList.remove("pill-disabled");
      addBtn.setAttribute("aria-disabled", "false");
    }
    if (hint) hint.textContent = "";
  }

  function prepareOpenState() {
    if (input) input.value = "";
    const cnt = getExistingEventFlagsCount();
    if (cnt >= MAX_EVENT_FLAGS) {
      disableAdd("固有フラグは最大2つです（これ以上追加できません）");
      return;
    }
    enableAdd();
  }

  function openFromOutside() { prepareOpenState(); open(); }

  document.addEventListener("openEventFlagSettings", () => { openFromOutside(); });

  window.UI = window.UI || {};
  window.UI.openEventFlagSettings = openFromOutside;

  openBtns.forEach((b) => {
    b.addEventListener("click", (e) => {
      window.UI?._stopAll?.(e);
      prepareOpenState();
      open();
    });
  });

  function closeWithRule() {
    close();
    const cnt = getExistingEventFlagsCount();
    if (cnt === 0) {
      window.UI?._requestReopenDisplaySettings?.({ forceEventFlags: false });
    }
  }

  closeBtn?.addEventListener("click", (e) => { window.UI?._stopAll?.(e); closeWithRule(); });
  cancelBtn?.addEventListener("click", (e) => { window.UI?._stopAll?.(e); closeWithRule(); });

  modal.addEventListener("click", (e) => { if (e.target === modal) closeWithRule(); });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!isOpen()) return;
    closeWithRule();
  });

  // add
  addBtn?.addEventListener("click", async (e) => {
    window.UI?._stopAll?.(e);

    const eventId = getEventIdForSave();
    if (!eventId) { window.UI?.showMessage?.("イベント作成後に固有フラグを追加できます"); return; }

    const name = (input?.value || "").trim();
    if (!name) { window.UI?.showMessage?.("フラグ名を入力してください"); return; }

    const cnt = getExistingEventFlagsCount();
    if (cnt >= MAX_EVENT_FLAGS) { window.UI?.showMessage?.("固有フラグは最大2つです"); return; }

    const existingNames = Array.from(document.querySelectorAll("th.event-flag-header .flag-name"))
      .map((el) => (el.textContent || "").trim())
      .filter(Boolean);
    if (existingNames.includes(name)) { window.UI?.showMessage?.("同じ名前の固有フラグが既にあります"); return; }

    const apiHooks = document.getElementById("event-flag-api-hooks");
    const url = (apiHooks?.dataset?.addEventFlagUrl || "").trim();
    if (!url) { window.UI?.showMessage?.("API未設定（addEventFlagUrl が必要）"); return; }

    try {
      const csrftoken = window.UI?.getCsrfToken?.() || "";
      if (!csrftoken) { window.UI?.showMessage?.("CSRFトークンが取得できません"); return; }

      const payload = { event_id: String(eventId), name: String(name) };
      const adminTokenPicked = window.UI?._pickAdminToken?.() || "";
      if (adminTokenPicked) payload.admin_token = adminTokenPicked;

      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrftoken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        console.warn("[add_event_flag] failed", { status: res.status, url, sent: payload, resp: data });
        const err = (data?.error || "").toString();
        if (res.status === 403 || err === "forbidden") window.UI?.showMessage?.("権限がありません（幹事ページで操作してください）");
        else if (err === "duplicate_name") window.UI?.showMessage?.("同じ名前の固有フラグが既にあります");
        else if (err === "limit_reached") window.UI?.showMessage?.("固有フラグは最大2つです");
        else if (err === "name_too_long") window.UI?.showMessage?.("フラグ名が長すぎます（20文字以内）");
        else window.UI?.showMessage?.("追加に失敗しました");
        return;
      }

      window.UI?.showMessage?.("固有フラグを追加しました");
      close();

      document.dispatchEvent(new CustomEvent("eventFlagsUpdated", { detail: { action: "add", ...data } }));

      // ★FIX：固有フラグ変更が入ったので、イベント編集モーダルの更新ボタンをアクティブ化
      window.UI?._markClubEventModalDirty?.();

      // ★追加成功後：Display Settings を event_flags ON で再表示（ページリロード無し）
      window.UI?._requestReopenDisplaySettings?.({ forceEventFlags: true });
    } catch (err) {
      console.warn("[add_event_flag] exception", err);
      window.UI?.showMessage?.("追加に失敗しました");
    }
  });
})();

// ============================================================
// Event Flag Menu Modal（追加/削除の選択）
// ============================================================
(function initEventFlagMenuModal() {
  const modal = document.getElementById("event-flag-menu-modal");
  if (!modal) return;
  if (modal.dataset.wired === "1") return;
  modal.dataset.wired = "1";

  const closeBtn = document.getElementById("close-event-flag-menu-modal");
  const addBtn = document.getElementById("event-flag-menu-add-btn");
  const delBtn = document.getElementById("event-flag-menu-delete-btn");

  const MAX_EVENT_FLAGS = 2;

  function isOpen() { return modal.classList.contains("is-open"); }
  function open() { modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); }
  function close() { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }

  function getExistingEventFlagsCount() {
    const ths = document.querySelectorAll("th.event-flag-header");
    return ths ? ths.length : 0;
  }

  function updateButtonsState() {
    const count = getExistingEventFlagsCount();
    if (addBtn) {
      const disabled = count >= MAX_EVENT_FLAGS;
      addBtn.disabled = disabled;
      addBtn.setAttribute("aria-disabled", disabled ? "true" : "false");
    }
    if (delBtn) {
      const disabled = count === 0;
      delBtn.disabled = disabled;
      delBtn.setAttribute("aria-disabled", disabled ? "true" : "false");
    }
  }

  document.addEventListener("openEventFlagMenu", () => { updateButtonsState(); open(); });

  closeBtn?.addEventListener("click", (e) => { window.UI?._stopAll?.(e); close(); });

  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!isOpen()) return;
    close();
  });

  addBtn?.addEventListener("click", (e) => {
    window.UI?._stopAll?.(e);
    if (addBtn.disabled) return;
    close();
    document.dispatchEvent(new CustomEvent("openEventFlagSettings"));
  });

  delBtn?.addEventListener("click", (e) => {
    window.UI?._stopAll?.(e);
    if (delBtn.disabled) return;
    close();
    document.dispatchEvent(new CustomEvent("openEventFlagDelete"));
  });
})();

// ============================================================
// Event Flag Delete Modal（イベント固有フラグ削除）
// ============================================================
(function initEventFlagDeleteModal() {
  const modal = document.getElementById("event-flag-delete-modal");
  if (!modal) return;
  if (modal.dataset.wired === "1") return;
  modal.dataset.wired = "1";

  const closeBtn = document.getElementById("close-event-flag-delete-modal");
  const selectEl = document.getElementById("event-flag-delete-select");
  const okBtn = document.getElementById("event-flag-delete-ok-btn");

  function isOpen() { return modal.classList.contains("is-open"); }
  function open() { modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); }
  function close() { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }

  function getEventId() {
    const el = document.getElementById("club-event-event-id");
    const v = (el?.value || "").trim();
    if (v) return v;
    const hooks = document.getElementById("page-hooks");
    return (hooks?.dataset?.eventId || "").trim();
  }

  function rebuildOptionsFromTable() {
    if (!selectEl) return;
    selectEl.innerHTML = `<option value="">-- 選択 --</option>`;
    const headers = Array.from(document.querySelectorAll("th.event-flag-header"));
    headers.forEach((th) => {
      const id = (th.dataset.eventFlagId || "").trim();
      const nameEl = th.querySelector(".flag-name");
      const name = (nameEl?.textContent || "").trim();
      if (!id || !name) return;
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = name;
      selectEl.appendChild(opt);
    });
  }

  document.addEventListener("openEventFlagDelete", () => { rebuildOptionsFromTable(); open(); });

  closeBtn?.addEventListener("click", (e) => { window.UI?._stopAll?.(e); close(); });

  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!isOpen()) return;
    close();
  });

  okBtn?.addEventListener("click", async (e) => {
    window.UI?._stopAll?.(e);

    const eventFlagId = (selectEl?.value || "").trim();
    if (!eventFlagId) { window.UI?.showMessage?.("削除する固有フラグを選択してください"); return; }

    const eventId = getEventId();
    if (!eventId) { window.UI?.showMessage?.("イベントIDが取得できません"); return; }

    const apiHooks = document.getElementById("event-flag-api-hooks");
    const url = (apiHooks?.dataset?.deleteEventFlagUrl || "").trim();
    if (!url) { window.UI?.showMessage?.("削除API未設定（deleteEventFlagUrl が必要）"); return; }

    const csrftoken = window.UI?.getCsrfToken?.() || "";
    if (!csrftoken) { window.UI?.showMessage?.("CSRFトークンが取得できません"); return; }

    const countBefore = document.querySelectorAll("th.event-flag-header").length;

    try {
      const payload = { event_id: String(eventId), event_flag_id: String(eventFlagId) };
      const adminTokenPicked = window.UI?._pickAdminToken?.() || "";
      if (adminTokenPicked) payload.admin_token = adminTokenPicked;

      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrftoken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        console.warn("[delete_event_flag] failed", { status: res.status, url, sent: payload, resp: data });
        window.UI?.showMessage?.("削除に失敗しました");
        return;
      }

      window.UI?.showMessage?.("固有フラグを削除しました");
      close();

      document.dispatchEvent(new CustomEvent("eventFlagsUpdated", {
        detail: { action: "delete", event_id: String(eventId), event_flag_id: String(eventFlagId), ...data }
      }));

      // ★FIX：固有フラグ変更が入ったので、イベント編集モーダルの更新ボタンをアクティブ化
      window.UI?._markClubEventModalDirty?.();

      // ★削除成功後：Display Settings に戻る（残り0なら OFF）
      const countAfter = Math.max(0, countBefore - 1);
      window.UI?._requestReopenDisplaySettings?.({ forceEventFlags: countAfter > 0 });
    } catch (err) {
      console.warn("[delete_event_flag] exception", err);
      window.UI?.showMessage?.("削除に失敗しました");
    }
  });
})();

// ============================================================
// Display Settings Modal: "固有フラグ 編集" pill
// ============================================================
(function initDisplaySettingsEventFlagEditPill() {
  function wire() {
    const btns = document.querySelectorAll(".js-open-event-flag-menu");
    if (!btns || !btns.length) return;

    btns.forEach((btn) => {
      if (btn.dataset.wired === "1") return;
      btn.dataset.wired = "1";

      btn.addEventListener("click", (e) => {
        window.UI?._stopAll?.(e);
        document.dispatchEvent(new CustomEvent("openEventFlagMenu"));
      });
    });
  }

  document.addEventListener("DOMContentLoaded", wire);

  document.addEventListener("reopenDisplaySettings", () => {
    setTimeout(wire, 0);
  });
})();
