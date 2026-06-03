// tennis/static/tennis/club_settings.js

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}

document.addEventListener("DOMContentLoaded", () => {
  const csrftoken = getCookie("csrftoken");

  function getAdminTokenFromEl(el) {
    return (el?.dataset?.adminToken || "").trim();
  }

  // ============================================================
  // [Z] デフォルト表示設定（クラブ単位）
  //   - チェックトグルで即保存（保存ボタン無し）
  //   - イベントページの「表示設定」モーダルと同じ ds-toggle UI を流用
  // ============================================================
  (function initClubDisplaySettings() {
    const root = document.getElementById("club-display-settings-form");
    if (!root) return;

    const status = document.getElementById("club-display-settings-status");
    const clubId = (root.dataset.clubId || "").trim();
    const adminToken = (root.dataset.adminToken || "").trim();
    const saveUrl = (root.dataset.saveUrl || "").trim();
    if (!clubId || !adminToken || !saveUrl) return;

    function setStatus(text, ok) {
      if (!status) return;
      status.textContent = text;
      status.style.color = ok ? "#0a7a3a" : "#a00";
    }

    function readToggleState(btn) {
      return !!btn?.classList.contains("is-on");
    }

    function setToggleState(btn, on) {
      if (!btn) return;
      btn.classList.toggle("is-on", !!on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", !!on);
        icon.classList.toggle("check-off", !on);
      }
    }

    function collectSettings() {
      const get = (key) => {
        const btn = root.querySelector(`.ds-toggle[data-key="${key}"]`);
        return readToggleState(btn);
      };
      return {
        common_flags: get("common_flags"),
        event_flags:  get("event_flags"),
        class:        get("class"),
        schedule:     get("schedule"),
      };
    }

    async function save(payload) {
      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);
      fd.append("settings_json", JSON.stringify(payload));

      const resp = await fetch(saveUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken || "" },
        body: fd,
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok) {
        throw new Error(data?.error || "save_failed");
      }
      return data.settings;
    }

    let saving = false;
    async function onToggle(btn) {
      if (saving) return;
      const prevState = readToggleState(btn);
      const newState = !prevState;
      setToggleState(btn, newState);

      saving = true;
      setStatus("保存中…", true);
      try {
        const saved = await save(collectSettings());
        root.dataset.currentSettings = JSON.stringify(saved);
        setStatus("保存しました", true);
      } catch (err) {
        console.error("[club display settings] save failed", err);
        // 失敗時は UI を元に戻す
        setToggleState(btn, prevState);
        setStatus("保存に失敗しました", false);
      } finally {
        saving = false;
      }
    }

    // ボタン本体／行どこを押しても反応
    root.addEventListener("click", (e) => {
      const toggleBtn = e.target.closest(".ds-toggle[data-key]");
      const row = e.target.closest(".ds-row");
      if (!toggleBtn && !row) return;
      const btn = toggleBtn || row.querySelector(".ds-toggle[data-key]");
      if (!btn) return;
      e.preventDefault();
      onToggle(btn);
    });
  })();

  // ============================================================
  // [Z2] 戦績ランキングのルール（クラブ単位）
  //   - プリセット選択で初期値を流し込み、各項目を上書き可
  //   - 「保存」ボタンで全フィールドをまとめて保存
  // ============================================================
  (function initClubRankingSettings() {
    const root = document.getElementById("club-ranking-settings-form");
    if (!root) return;

    const status = document.getElementById("club-ranking-settings-status");
    const saveBtn = document.getElementById("club-ranking-settings-save");
    const clubId = (root.dataset.clubId || "").trim();
    const adminToken = (root.dataset.adminToken || "").trim();
    const saveUrl = (root.dataset.saveUrl || "").trim();
    if (!clubId || !adminToken || !saveUrl) return;

    let presetDefaults = {};
    try {
      presetDefaults = JSON.parse(root.dataset.presetDefaults || "{}");
    } catch (_) {
      presetDefaults = {};
    }

    function setStatus(text, ok) {
      if (!status) return;
      status.textContent = text;
      status.style.color = ok ? "#0a7a3a" : "#a00";
    }

    const numInput = (key) => root.querySelector(`input[type="number"][data-rk="${key}"]`);
    const drawToggle = () => root.querySelector('.rk-toggle[data-rk="count_draws"]');

    function getSelectedPreset() {
      const checked = root.querySelector('input[name="rk-preset"]:checked');
      return checked ? checked.value : "winrate";
    }

    function readToggle(btn) {
      return !!btn?.classList.contains("is-on");
    }

    function setToggle(btn, on) {
      if (!btn) return;
      btn.classList.toggle("is-on", !!on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", !!on);
        icon.classList.toggle("check-off", !on);
      }
    }

    // プリセットのデフォルト値を各コントロールへ流し込む
    function applyPresetDefaults(preset) {
      const d = presetDefaults[preset];
      if (!d) return;
      setToggle(drawToggle(), !!d.count_draws);
      const set = (key, v) => { const el = numInput(key); if (el) el.value = v; };
      set("points_win", d.points_win);
      set("points_draw", d.points_draw);
      set("points_loss", d.points_loss);
      set("min_matches", d.min_matches);
    }

    function collectSettings() {
      const num = (key, fallback) => {
        const el = numInput(key);
        const v = parseFloat(el?.value);
        return Number.isFinite(v) ? v : fallback;
      };
      return {
        preset: getSelectedPreset(),
        count_draws: readToggle(drawToggle()),
        points_win: num("points_win", 3),
        points_draw: num("points_draw", 1),
        points_loss: num("points_loss", 0),
        min_matches: Math.max(0, Math.trunc(num("min_matches", 3))),
      };
    }

    async function save(payload) {
      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);
      fd.append("settings_json", JSON.stringify(payload));

      const resp = await fetch(saveUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken || "" },
        body: fd,
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok) {
        throw new Error(data?.error || "save_failed");
      }
      return data.settings;
    }

    // プリセット切替で初期値を流し込み
    root.addEventListener("change", (e) => {
      if (e.target?.name === "rk-preset") {
        applyPresetDefaults(e.target.value);
      }
    });

    // 引き分けトグル
    root.addEventListener("click", (e) => {
      const btn = e.target.closest('.rk-toggle[data-rk="count_draws"]');
      if (!btn) return;
      e.preventDefault();
      setToggle(btn, !readToggle(btn));
    });

    let saving = false;
    saveBtn?.addEventListener("click", async () => {
      if (saving) return;
      saving = true;
      setStatus("保存中…", true);
      try {
        const saved = await save(collectSettings());
        root.dataset.currentSettings = JSON.stringify(saved);
        setStatus("保存しました", true);
      } catch (err) {
        console.error("[club ranking settings] save failed", err);
        setStatus("保存に失敗しました", false);
      } finally {
        saving = false;
      }
    });
  })();

  // ============================================================
  // [A] クラブ名変更（保存あり）
  // ============================================================
  (function initClubRenameModal() {
    const hooks = document.getElementById("club-rename-hooks");
    const nameDisplay = document.getElementById("club-name-display");

    const modal = document.getElementById("club-rename-modal");
    const closeBtn = document.getElementById("club-rename-modal-close");
    const form = document.getElementById("club-rename-modal-form");
    const input = document.getElementById("club-rename-input");

    if (!hooks || !nameDisplay || !modal || !form || !input) return;

    const renameUrl = hooks.dataset.renameUrl;
    const clubId = hooks.dataset.clubId;

    function openRenameModal() {
      const current = (hooks.dataset.currentName || nameDisplay.textContent || "").trim();
      input.value = current;
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      setTimeout(() => input.focus(), 0);
    }

    function closeRenameModal() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
    }

    nameDisplay.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openRenameModal();
    });

    closeBtn?.addEventListener("click", closeRenameModal);

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeRenameModal();
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const name = (input.value || "").trim();
      if (!name) {
        UI.showMessage("クラブ名を入力してください。", 2400);
        return;
      }

      const adminToken = getAdminTokenFromEl(hooks);

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);
      fd.append("name", name);

      try {
        const r = await fetch(renameUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });
        const data = await r.json().catch(() => ({}));

        if (!r.ok || !data.ok) {
          UI.showMessage("保存に失敗しました。", 2600);
          return;
        }

        nameDisplay.textContent = data.name || name;
        hooks.dataset.currentName = data.name || name;

        closeRenameModal();
        UI.showMessage("クラブ名を更新しました。", 2000);
      } catch (err) {
        UI.showMessage("保存に失敗しました（ネットワーク）。", 2600);
      }
    });
  })();

  // ============================================================
  // [B] フラグ追加 / 削除（保存あり）
  //  - 追加は「先に名前を決める」モーダル経由
  //  - 削除は「選択モーダル」方式
  // ============================================================
  (function initFlagsAddDelete() {
    const addBtn = document.getElementById("club-add-flag-btn");
    const delBtn = document.getElementById("club-delete-flag-btn");

    // --- 追加モーダル（_ui_modals.html 側に存在する前提）
    const addModal = document.getElementById("flag-add-modal");
    const addCloseBtn = document.getElementById("close-flag-add-modal");
    const addForm = document.getElementById("flag-add-form");
    const addInput = document.getElementById("flag-add-input");
    const addMode = document.getElementById("flag-add-input-mode"); // check / digit

    function openAddModal() {
      if (!addModal || !addInput) return;

      addInput.value = "";
      if (addMode) addMode.value = "check";

      addModal.classList.add("is-open");
      addModal.setAttribute("aria-hidden", "false");
      setTimeout(() => addInput.focus(), 0);
    }

    function closeAddModal() {
      if (!addModal) return;
      addModal.classList.remove("is-open");
      addModal.setAttribute("aria-hidden", "true");
    }

    if (addBtn) {
      addBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (addBtn.disabled) return;
        openAddModal();
      });
    }

    addCloseBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeAddModal();
    });

    addModal?.addEventListener("click", (e) => {
      if (e.target === addModal) closeAddModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && addModal?.classList.contains("is-open")) {
        closeAddModal();
      }
    });

    if (addForm && addBtn) {
      addForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const name = (addInput?.value || "").trim();
        if (!name) {
          UI.showMessage("フラグ名を入力してください。", 2400);
          return;
        }

        const clubId = (addBtn.dataset.clubId || "").trim();
        const url = (addBtn.dataset.addFlagUrl || "").trim();
        const adminToken = getAdminTokenFromEl(addBtn);
        if (!clubId || !url) return;

        const inputMode = (addMode?.value || "check").trim();

        const fd = new FormData();
        fd.append("club_id", clubId);
        fd.append("admin_token", adminToken);
        fd.append("name", name);
        fd.append("input_mode", inputMode);

        try {
          const r = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));

          if (!r.ok || data.error) {
            if (data.error === "max_reached") {
              UI.showMessage(`フラグは最大 ${data.max} 個までです。`, 2600);
              addBtn.disabled = true;
            } else {
              UI.showMessage("フラグ追加に失敗しました。", 2600);
            }
            return;
          }

          closeAddModal();
          window.location.reload();
        } catch (err) {
          UI.showMessage("フラグ追加に失敗しました（ネットワーク）。", 2600);
        }
      });
    }

    // ------------------------
    // 削除（選択モーダル方式）
    // ------------------------
    (function initFlagDeleteModal() {
      if (!delBtn) return;

      const delModal = document.getElementById("flag-delete-modal");
      const delCloseBtn = document.getElementById("close-flag-delete-modal");
      const delSelect = document.getElementById("flag-delete-select");
      const delOkBtn = document.getElementById("flag-delete-ok-btn");

      if (!delModal || !delSelect || !delOkBtn) return;

      function openDelModal() {
        if (delBtn.disabled) return;
        delSelect.value = "";
        delModal.classList.add("is-open");
        delModal.setAttribute("aria-hidden", "false");
        setTimeout(() => delSelect.focus(), 0);
      }

      function closeDelModal() {
        delModal.classList.remove("is-open");
        delModal.setAttribute("aria-hidden", "true");
        delSelect.value = "";
      }

      delBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openDelModal();
      });

      delCloseBtn?.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDelModal();
      });

      delModal.addEventListener("click", (e) => {
        if (e.target === delModal) closeDelModal();
      });

      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && delModal.classList.contains("is-open")) closeDelModal();
      });

      delOkBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const flagId = (delSelect.value || "").trim();
        if (!flagId) {
          UI.showMessage("削除するフラグを選択してください。", 2200);
          return;
        }

        const clubId = (delBtn.dataset.clubId || "").trim();
        const url = (delBtn.dataset.deleteFlagUrl || "").trim();
        if (!clubId || !url) return;

        const adminToken = getAdminTokenFromEl(delBtn);

        const fd = new FormData();
        fd.append("club_id", clubId);
        fd.append("admin_token", adminToken);
        fd.append("flag_id", flagId);

        try {
          const r = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));

          if (!r.ok || data.error) {
            UI.showMessage("削除できませんでした。", 2600);
            return;
          }

          closeDelModal();
          window.location.reload();
        } catch (err) {
          UI.showMessage("削除に失敗しました（ネットワーク）。", 2600);
        }
      });
    })();
  })();

  // ============================================================
  // [C] フラグ名称変更（保存あり）
  //  - ダミーの participants-table は廃止
  //  - flags-table の「フラグ名（span.flag-name）」をクリックで編集
  // ============================================================
  (function initFlagRenameModal() {
    const table = document.getElementById("flags-table");
    if (!table) return;

    const hooks = document.getElementById("flag-hooks");
    if (!hooks) return;

    const renameUrl = (hooks.dataset.renameFlagUrl || "").trim();
    const clubId = (hooks.dataset.clubId || "").trim();
    const adminToken = (hooks.dataset.adminToken || "").trim();
    if (!renameUrl || !clubId || !adminToken) return;

    const modal = document.getElementById("flag-rename-modal");
    const closeBtn = document.getElementById("close-flag-rename-modal");
    const form = document.getElementById("flag-rename-form");
    const input = document.getElementById("flag-rename-input");
    const hiddenFlagId = document.getElementById("flag-rename-flag-id");

    if (!modal || !closeBtn || !form || !input || !hiddenFlagId) return;

    let currentSpan = null;

    function openModal(flagId, currentName, spanEl) {
      currentSpan = spanEl || null;
      hiddenFlagId.value = flagId;
      input.value = currentName || "";
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      setTimeout(() => input.focus(), 0);
    }

    function closeModal() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      hiddenFlagId.value = "";
      currentSpan = null;
    }

    closeBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeModal();
    });

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    });

    // フラグ名クリックで開く
    table.addEventListener("click", (e) => {
      const nameEl = e.target.closest(".flag-name");
      if (!nameEl) return;

      const tr = nameEl.closest("tr[data-flag-id]");
      if (!tr) return;

      e.preventDefault();
      e.stopPropagation();

      const flagId = (tr.dataset.flagId || "").trim();
      if (!flagId) return;

      const currentName = (nameEl.textContent || "").trim();
      openModal(flagId, currentName, nameEl);
    });

    // 保存
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const flagId = (hiddenFlagId.value || "").trim();
      const name = (input.value || "").trim();

      if (!flagId) return;
      if (!name) {
        UI.showMessage("フラグ名を入力してください。", 2400);
        return;
      }

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);
      fd.append("flag_id", flagId);
      fd.append("name", name);

      try {
        const r = await fetch(renameUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });
        const data = await r.json().catch(() => ({}));

        if (!r.ok || data.error) {
          UI.showMessage("フラグ名の変更に失敗しました。", 2600);
          return;
        }

        if (currentSpan) currentSpan.textContent = data.name || name;

        closeModal();
        UI.showMessage("フラグ名を更新しました。", 1800);
      } catch (err) {
        console.error(err);
        UI.showMessage("フラグ名の変更に失敗しました（ネットワーク）。", 2600);
      }
    });
  })();

  // =============================
  // [B] メンバー管理（固定/非固定のみ）
  // =============================
  (function initMemberManage() {
    const hooks = document.getElementById("member-hooks");
    if (!hooks) return;

    const clubId = hooks.dataset.clubId;
    const adminToken = hooks.dataset.adminToken;

    const addUrl = hooks.dataset.addUrl;
    const renameUrl = hooks.dataset.renameUrl;
    const toggleFixedUrl = hooks.dataset.toggleFixedUrl;

    const input = document.getElementById("member-add-input");
    const addBtn = document.getElementById("member-add-btn");
    const table = document.getElementById("members-table");

    const post = async (url, fd) => {
      const res = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken },
        body: fd,
      });
      return await res.json();
    };

    // 追加
    if (addBtn) {
      addBtn.addEventListener("click", async () => {
        const name = (input?.value || "").trim();
        if (!name) return;

        const fd = new FormData();
        fd.append("club_id", clubId);
        fd.append("admin_token", adminToken);
        fd.append("display_name", name);

        const data = await post(addUrl, fd);
        if (!data.ok) {
          alert("追加に失敗しました: " + (data.error || ""));
          return;
        }
        location.reload();
      });
    }

    if (!table) return;

    // 名前は <a class="member-name" href="..."> 個人ページへのリンクになっており、
    // 旧モーダル経由のリネーム・削除はここでは扱わない（個人ページ側で処理）。

    // fixed トグルのみ
    table.addEventListener("click", async (e) => {
      const btn = e.target.closest(".member-fixed-toggle");
      if (!btn) return;

      const tr = btn.closest("tr[data-member-id]");
      if (!tr) return;

      const memberId = tr.dataset.memberId;
      const isOn = btn.classList.contains("is-on");
      const next = !isOn;

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);
      fd.append("member_id", memberId);
      fd.append("checked", next ? "true" : "false");

      const data = await post(toggleFixedUrl, fd);
      if (!data.ok) {
        alert("更新に失敗しました: " + (data.error || ""));
        return;
      }

      btn.classList.toggle("is-on", next);
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", next);
        icon.classList.toggle("check-off", !next);
      }
    });
  })();

  // ============================================================
  // [NEW] Class management + member class assignment (dropdown)
  // ============================================================
  (function initClasses() {
    const hooks = document.getElementById("class-hooks");
    if (!hooks) return;

    const clubId = hooks.dataset.clubId;
    const adminToken = hooks.dataset.adminToken;
    const urlAdd = hooks.dataset.addUrl;
    const urlRename = hooks.dataset.renameUrl;
    const urlDelete = hooks.dataset.deleteUrl;
    const urlSetMember = hooks.dataset.setMemberUrl;
    const csrftoken = getCookie("csrftoken");

    const classesTable = document.getElementById("classes-table");
    const membersTable = document.getElementById("members-table");

    const renameModal = document.getElementById("class-rename-modal");
    const renameClose = document.getElementById("class-rename-modal-close");
    const renameForm = document.getElementById("class-rename-modal-form");
    const renameMode = document.getElementById("class-rename-mode");
    const renameClassId = document.getElementById("class-rename-class-id");
    const renameInput = document.getElementById("class-rename-input");

    function openModal(modal) {
      if (!modal) return;
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      modal.style.zIndex = "3500";
    }
    function closeModal(modal) {
      if (!modal) return;
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      modal.style.zIndex = "";
    }
    renameClose?.addEventListener("click", (e) => {
      e.preventDefault();
      closeModal(renameModal);
    });

    function postForm(url, fd) {
      return fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken || "" },
        body: fd,
      }).then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) throw new Error(data.error || "not_ok");
        return data;
      });
    }

    function collectClassesFromTable() {
      const rows = Array.from(classesTable?.querySelectorAll("tbody tr") || []);
      return rows
        .map((tr) => ({
          id: (tr.dataset.classId || "").trim(),
          name: (tr.querySelector(".class-name")?.textContent || "").trim(),
        }))
        .filter((x) => x.id && x.name);
    }

    function syncMemberSelectOptions() {
      if (!membersTable) return;

      const classes = collectClassesFromTable();
      const selects = Array.from(membersTable.querySelectorAll("select.member-class-select"));

      selects.forEach((sel) => {
        const current = (sel.value || "").trim();
        const prev = (sel.dataset.prev || "").trim();

        sel.innerHTML = "";

        const emptyOpt = document.createElement("option");
        emptyOpt.value = "";
        emptyOpt.textContent = "";
        sel.appendChild(emptyOpt);

        classes.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = String(c.id);
          opt.textContent = c.name;
          sel.appendChild(opt);
        });

        const exists = classes.some((c) => String(c.id) === String(current));
        const nextVal = exists ? current : "";

        sel.value = nextVal;
        sel.dataset.prev = nextVal;

        if (!exists && prev && prev === current) {
          sel.dataset.prev = "";
        }
      });
    }

    const addBtn = document.getElementById("club-add-class-btn");
    addBtn?.addEventListener("click", () => {
      if (!renameMode || !renameClassId || !renameInput) return;

      renameMode.value = "create";
      renameClassId.value = "";
      renameInput.value = "";
      openModal(renameModal);
      setTimeout(() => renameInput.focus(), 0);
    });

    classesTable?.addEventListener("click", (e) => {
      const nameEl = e.target.closest(".class-name");
      if (!nameEl) return;

      const tr = nameEl.closest("tr");
      const cid = (tr?.dataset?.classId || "").trim();
      if (!cid) return;

      if (!renameMode || !renameClassId || !renameInput) return;

      renameMode.value = "rename";
      renameClassId.value = cid;
      renameInput.value = (nameEl.textContent || "").trim();
      openModal(renameModal);
      setTimeout(() => renameInput.focus(), 0);
    });

    renameForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const mode = (renameMode?.value || "").trim();
      const name = (renameInput?.value || "").trim();
      if (!name) return;

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);

      try {
        if (mode === "create") {
          if (!urlAdd) throw new Error("missing_add_url");
          fd.append("name", name);

          const data = await postForm(urlAdd, fd);

          const tbody = classesTable?.querySelector("tbody");
          if (tbody && data?.class?.id && data?.class?.name) {
            const tr = document.createElement("tr");
            tr.dataset.classId = data.class.id;
            tr.innerHTML = `
              <td>${tbody.children.length + 1}</td>
              <td>
                <span class="class-name" style="cursor:pointer; text-decoration:underline; font-weight:700;"
                      title="クリックして変更">${data.class.name}</span>
              </td>`;
            tbody.appendChild(tr);
          }

          syncMemberSelectOptions();
          UI?.showMessage?.("クラスを追加しました", 1400);
        } else {
          if (!urlRename) throw new Error("missing_rename_url");
          const cid = (renameClassId?.value || "").trim();
          if (!cid) return;

          fd.append("class_id", cid);
          fd.append("name", name);
          await postForm(urlRename, fd);

          const tr = classesTable?.querySelector(`tr[data-class-id="${cid}"]`);
          const el = tr?.querySelector(".class-name");
          if (el) el.textContent = name;

          syncMemberSelectOptions();
          UI?.showMessage?.("クラス名を変更しました", 1400);
        }

        closeModal(renameModal);
      } catch (err) {
        console.error(err);
        UI?.showMessage?.("保存に失敗しました", 2000);
      }
    });

    // ------------------------
    // クラス削除（選択モーダル方式）★NEW
    // ------------------------
    (function initClassDeleteModal() {
      const delBtn = document.getElementById("club-delete-class-btn");
      if (!delBtn) return;

      const delModal = document.getElementById("class-delete-modal");
      const delCloseBtn = document.getElementById("close-class-delete-modal");
      const delSelect = document.getElementById("class-delete-select");
      const delOkBtn = document.getElementById("class-delete-ok-btn");

      if (!delModal || !delSelect || !delOkBtn) return;

      function rebuildClassDeleteOptions() {
        // classesTable の最新状態から select を作り直す（追加/名称変更にも追従）
        const classes = collectClassesFromTable();

        delSelect.innerHTML = "";
        const head = document.createElement("option");
        head.value = "";
        head.textContent = "-- 選択 --";
        delSelect.appendChild(head);

        classes.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = String(c.id);
          opt.textContent = c.name;
          delSelect.appendChild(opt);
        });
      }

      function openDelModal() {
        if (delBtn.disabled) return;
        rebuildClassDeleteOptions();
        delSelect.value = "";

        delModal.classList.add("is-open");
        delModal.setAttribute("aria-hidden", "false");
        setTimeout(() => delSelect.focus(), 0);
      }

      function closeDelModal() {
        delModal.classList.remove("is-open");
        delModal.setAttribute("aria-hidden", "true");
        delSelect.value = "";
      }

      delBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openDelModal();
      });

      delCloseBtn?.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDelModal();
      });

      delModal.addEventListener("click", (e) => {
        if (e.target === delModal) closeDelModal();
      });

      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && delModal.classList.contains("is-open")) closeDelModal();
      });

      delOkBtn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const cid = (delSelect.value || "").trim();
        if (!cid) {
          UI?.showMessage?.("削除するチーム名を選択してください。", 2200);
          return;
        }

        if (!urlDelete) return;

        const fd = new FormData();
        fd.append("club_id", clubId);
        fd.append("admin_token", adminToken);
        fd.append("class_id", cid);

        try {
          await postForm(urlDelete, fd);

          // classesTable から該当行を消す
          const tr = classesTable?.querySelector(`tr[data-class-id="${cid}"]`);
          tr?.remove();

          // 連番を振り直す
          Array.from(classesTable?.querySelectorAll("tbody tr") || []).forEach((row, i) => {
            const td = row.querySelector("td");
            if (td) td.textContent = String(i + 1);
          });

          // members 側の select も同期
          syncMemberSelectOptions();

          // 削除ボタンの disabled を再評価
          const remain = (classesTable?.querySelectorAll("tbody tr") || []).length;
          delBtn.disabled = remain === 0;

          closeDelModal();
          UI?.showMessage?.("削除しました。", 1800);
        } catch (err) {
          console.error(err);
          UI?.showMessage?.("削除に失敗しました。", 2200);
        }
      });
    })();

    membersTable?.querySelectorAll("select.member-class-select").forEach((sel) => {
      sel.dataset.prev = (sel.value || "").trim();
    });

    membersTable?.addEventListener("change", async (e) => {
      const sel = e.target.closest("select.member-class-select");
      if (!sel) return;

      const memberId = (sel.dataset.memberId || "").trim();
      const classId = (sel.value || "").trim();
      if (!memberId) return;

      const prev = (sel.dataset.prev || "").trim();

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("admin_token", adminToken);
      fd.append("member_id", memberId);
      fd.append("class_id", classId);

      try {
        if (!urlSetMember) throw new Error("missing_set_member_url");
        await postForm(urlSetMember, fd);

        sel.dataset.prev = classId;
        // UI?.showMessage?.("クラスを更新しました", 1400);
      } catch (err) {
        console.error(err);
        sel.value = prev;
        UI?.showMessage?.("更新に失敗しました", 2000);
      }
    });

    syncMemberSelectOptions();
  })();
});
