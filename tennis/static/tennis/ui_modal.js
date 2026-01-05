// tennis/static/tennis/ui_modal.js
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
// Display Settings Modal (button toggles版)
// ============================================================
(function initDisplaySettingsModal() {
  const modal = document.getElementById("display-settings-modal");
  if (!modal) return;
  if (modal.dataset.wired === "1") return;
  modal.dataset.wired = "1";

  const openBtn = document.querySelector(".js-open-display-settings"); // club-event-modal側
  const closeBtn = document.getElementById("close-display-settings-modal");
  const okBtn = document.getElementById("display-settings-ok");

  const STORAGE_KEY = "tennis_display_settings_v1";

  function isOpen() {
    return modal.classList.contains("is-open");
  }
  function open() {
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
  }
  function close() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
  }

  function getToggle(key) {
    return modal.querySelector(`.ds-toggle[data-key="${key}"]`);
  }
  function setToggle(key, on) {
    const btn = getToggle(key);
    if (!btn) return;
    const isOn = !!on;
    btn.classList.toggle("is-on", isOn);
    btn.setAttribute("aria-pressed", isOn ? "true" : "false");
    const icon = btn.querySelector(".check-icon");
    if (icon) {
      icon.classList.toggle("check-on", isOn);
      icon.classList.toggle("check-off", !isOn);
      icon.textContent = "✓";
    }
  }
  function readToggle(key) {
    const btn = getToggle(key);
    if (!btn) return true; // デフォルトON
    return btn.classList.contains("is-on");
  }

  // ★互換：過去の保存形式が show_flags/show_class/show_schedule の可能性がある
  function normalizeState(obj) {
    if (!obj || typeof obj !== "object") return null;

    // 新キーがあればそれを優先
    const hasNew =
      ("common_flags" in obj) || ("event_flags" in obj) || ("class" in obj) || ("schedule" in obj);

    if (hasNew) {
      return {
        common_flags: obj.common_flags !== false,
        event_flags: obj.event_flags !== false,
        class: obj.class !== false,
        schedule: obj.schedule !== false,
      };
    }

    // 旧キー → 新キー
    // show_flags = 共通フラグON/OFF とみなす
    return {
      common_flags: obj.show_flags !== false,
      event_flags: true,              // 旧データには無いのでデフォルトON
      class: obj.show_class !== false,
      schedule: obj.show_schedule !== false,
    };
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return normalizeState(JSON.parse(raw));
    } catch (e) {
      return null;
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {}
  }

  function readStateFromUI() {
    return {
      common_flags: readToggle("common_flags"),
      event_flags: readToggle("event_flags"),
      class: readToggle("class"),
      schedule: readToggle("schedule"),
    };
  }

  function writeStateToUI(state) {
    if (!state) return;
    setToggle("common_flags", state.common_flags !== false);
    setToggle("event_flags", state.event_flags !== false);
    setToggle("class", state.class !== false);
    setToggle("schedule", state.schedule !== false);
  }

  function notify(state) {
    document.dispatchEvent(new CustomEvent("displaySettingsChanged", { detail: state }));
  }

  function activateClubEventSubmit() {
    const btn = document.getElementById("club-event-submit-btn");
    if (!btn) return;
    btn.disabled = false;
    btn.classList.remove("pill-disabled");
    btn.setAttribute("aria-disabled", "false");
  }

  // 初期：保存があれば復元
  const saved = loadState();
  if (saved) writeStateToUI(saved);

  // 各トグルクリックでON/OFF切り替え（ボタン方式）
  modal.querySelectorAll(".ds-toggle").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const key = (btn.dataset.key || "").trim();
      if (!key) return;
      const next = !btn.classList.contains("is-on");
      setToggle(key, next);
    });
  });

  // open
  if (openBtn) {
    openBtn.addEventListener("click", (e) => {
      e.preventDefault();
      const s = loadState();
      if (s) writeStateToUI(s);
      open();
    });
  }

  // close: ×
  if (closeBtn) {
    closeBtn.addEventListener("click", (e) => {
      e.preventDefault();
      close();
    });
  }

  // ok: 保存＋通知＋更新有効化＋閉じる
  if (okBtn) {
    okBtn.addEventListener("click", (e) => {
      e.preventDefault();
      const state = readStateFromUI();
      saveState(state);
      notify(state);
      activateClubEventSubmit();
      close();
    });
  }

  document.addEventListener("displaySettingsChanged", () => {
    activateClubEventSubmit();
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) close();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!isOpen()) return;
    close();
  });
})();

// ============================================================
// Event Flag Settings Modal (固有フラグ名の入力)
//  - 今は「追加のみ」
//  - 保存先が必要なので event_id が無い(create)場合は保存できない
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

  function isOpen() {
    return modal.classList.contains("is-open");
  }
  function open() {
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
  }
  function close() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
  }

  function getEventIdForSave() {
    // club-event-modal(作成/編集) の hidden を優先
    const el = document.getElementById("club-event-event-id");
    const v = (el?.value || "").trim();
    if (v) return v;

    // eventページなら page-hooks から取れる
    const hooks = document.getElementById("page-hooks");
    const v2 = (hooks?.dataset?.eventId || "").trim();
    if (v2) return v2;

    return "";
  }

  // いま取れる範囲で「既存の固有フラグ数」を推定する
  function getExistingEventFlagsCount() {
    // event.html 側で <th class="flag-header event-flag-header" ...> を出しているのでそれを数える
    const ths = document.querySelectorAll("th.event-flag-header");
    if (ths && ths.length) return ths.length;

    // 将来用：page-hooks に入れておけばモーダルからも確実に取れる
    const hooks = document.getElementById("page-hooks");
    const c = (hooks?.dataset?.eventFlagsCount || "").trim();
    if (c && /^\d+$/.test(c)) return parseInt(c, 10);

    return null; // 不明
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
    if (hint) hint.textContent = "※ 1回の追加で1個だけ登録します";
  }

  function prepareOpenState() {
    if (input) input.value = "";

    const cnt = getExistingEventFlagsCount();
    if (cnt !== null && cnt >= MAX_EVENT_FLAGS) {
      disableAdd("固有フラグは最大2つです（これ以上追加できません）");
      return;
    }
    enableAdd();
  }

  // open
  openBtns.forEach((b) => {
    b.addEventListener("click", (e) => {
      e.preventDefault();
      prepareOpenState();
      open();
    });
  });

  // close
  closeBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    close();
  });
  cancelBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    close();
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) close();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!isOpen()) return;
    close();
  });

  // add（※APIは次に実装：1個追加するだけ）
  addBtn?.addEventListener("click", async (e) => {
    e.preventDefault();

    const eventId = getEventIdForSave();
    if (!eventId) {
      window.UI?.showMessage?.("イベント作成後に固有フラグを追加できます");
      return;
    }

    const name = (input?.value || "").trim();
    if (!name) {
      window.UI?.showMessage?.("フラグ名を入力してください");
      return;
    }

    // 既に2つあるなら弾く（わかる範囲で）
    const cnt = getExistingEventFlagsCount();
    if (cnt !== null && cnt >= MAX_EVENT_FLAGS) {
      window.UI?.showMessage?.("固有フラグは最大2つです");
      return;
    }

    // 既存名と重複なら弾く（eventページで見える範囲）
    const existingNames = Array.from(document.querySelectorAll("th.event-flag-header .flag-name"))
      .map((el) => (el.textContent || "").trim())
      .filter(Boolean);
    if (existingNames.includes(name)) {
      window.UI?.showMessage?.("同じ名前の固有フラグが既にあります");
      return;
    }

    const apiHooks = document.getElementById("event-flag-api-hooks");
    const url = (apiHooks?.dataset?.addEventFlagUrl || "").trim();
    if (!url) {
      window.UI?.showMessage?.("API未設定（add_event_flag_url が必要）");
      return;
    }

    try {
      const csrftoken = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrftoken,
        },
        body: JSON.stringify({ event_id: eventId, name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        window.UI?.showMessage?.("追加に失敗しました");
        return;
      }

      window.UI?.showMessage?.("固有フラグを追加しました");
      close();

      // 表の再描画は event.js 側で後ほど（ここでは通知だけ）
      document.dispatchEvent(new CustomEvent("eventFlagsUpdated", { detail: data }));
    } catch (err) {
      window.UI?.showMessage?.("追加に失敗しました");
    }
  });

  // 追加後に外部がUI更新した場合に備えて、次回openで判定できるようにする
})();
