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
  // ============================================================
  (function initFlagsAddDelete() {
    const addBtn = document.getElementById("club-add-flag-btn");
    const delBtn = document.getElementById("club-delete-flag-btn");

    // --- 共通モーダル（_ui_modals.html）
    const addModal = document.getElementById("flag-add-modal");
    const addCloseBtn = document.getElementById("close-flag-add-modal");
    const addForm = document.getElementById("flag-add-form");
    const addInput = document.getElementById("flag-add-input");

    function openAddModal() {
      if (!addModal || !addInput) return;
      addInput.value = "";
      addModal.classList.add("is-open");
      addModal.setAttribute("aria-hidden", "false");
      setTimeout(() => addInput.focus(), 0);
    }

    function closeAddModal() {
      if (!addModal) return;
      addModal.classList.remove("is-open");
      addModal.setAttribute("aria-hidden", "true");
    }

    // ------------------------
    // 追加ボタン → モーダルを開く
    // ------------------------
    if (addBtn) {
      addBtn.addEventListener("click", (e) => {
        e.preventDefault();
        if (addBtn.disabled) return;
        openAddModal();
      });
    }

    // × / 背景 / ESC で閉じる（共通ルール）
    addCloseBtn?.addEventListener("click", closeAddModal);
    addModal?.addEventListener("click", (e) => {
      if (e.target === addModal) closeAddModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && addModal?.classList.contains("is-open")) {
        closeAddModal();
      }
    });

    // ------------------------
    // モーダル submit → API
    // ------------------------
    if (addForm && addBtn) {
      addForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const name = (addInput.value || "").trim();
        if (!name) {
          UI.showMessage("フラグ名を入力してください。", 2400);
          return;
        }

        const clubId = addBtn.dataset.clubId;
        const url = addBtn.dataset.addFlagUrl;
        const adminToken = getAdminTokenFromEl(addBtn);
        if (!clubId || !url) return;

        const fd = new FormData();
        fd.append("club_id", clubId);
        fd.append("admin_token", adminToken);
        fd.append("name", name);

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
    // 削除（既存ロジックそのまま）
    // ------------------------
    if (delBtn) {
      delBtn.addEventListener("click", () => {
        if (delBtn.disabled) return;

        UI.confirm("最後に追加したフラグを削除します。よろしいですか？", {
          okText: "削除",
          onOk: async () => {
            const clubId = delBtn.dataset.clubId;
            const url = delBtn.dataset.deleteFlagUrl;
            if (!clubId || !url) return;

            const adminToken = getAdminTokenFromEl(delBtn);

            const fd = new FormData();
            fd.append("club_id", clubId);
            fd.append("admin_token", adminToken);

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

              window.location.reload();
            } catch (err) {
              UI.showMessage("削除に失敗しました（ネットワーク）。", 2600);
            }
          },
        });
      });
    }
  })();

  // ============================================================
  // [C] フラグ名称変更（保存あり）: eventの参加登録モーダルに揃える
  // ============================================================
  (function initFlagRenameModal() {
    const table = document.getElementById("participants-table");
    if (!table) return;

    const renameUrl = table.dataset.renameFlagUrl;
    if (!renameUrl) return;

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

    closeBtn.addEventListener("click", closeModal);

    // 背景クリックで閉じる（event側と同じ）
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    // ヘッダークリックで開く
    table.querySelectorAll(".flag-header[data-flag-id]").forEach((th) => {
      th.addEventListener("click", () => {
        const flagId = (th.dataset.flagId || "").trim();
        if (!flagId) return;

        const span = th.querySelector(".flag-name");
        const currentName = span ? span.textContent.trim() : "";

        openModal(flagId, currentName, span);
      });
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

      const adminToken = (table.dataset.adminToken || "").trim();
      const clubId = (table.dataset.clubId || "").trim();

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


  // ============================================================
  // [D] settings(ダミー): 出欠モーダル（保存しない / choiceで即閉じ）
  // ============================================================
  (function initAttendanceModalDummy() {
    const table = document.getElementById("participants-table");
    if (!table) return;
    if (table.dataset.mode !== "club_settings_dummy") return;

    const modal = document.getElementById("attendance-modal");
    if (!modal) return;

    const closeBtn = document.getElementById("close-attendance-modal");

    let currentBtn = null;

    function openModal(targetBtn) {
      currentBtn = targetBtn;
      // settings側は注意文を出す（必要なら）
      const note = document.getElementById("attendance-modal-note");
      if (note) note.style.display = "block";

      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      currentBtn = null;

      const note = document.getElementById("attendance-modal-note");
      if (note) note.style.display = "none";
    }

    // 開く（ダミーの出欠ボタン）
    table.addEventListener("click", (e) => {
      const btn = e.target.closest(".attendance-btn");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      openModal(btn);
    });

    // ×で閉じる
    closeBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeModal();
    });

    // 背景クリックで閉じる
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    // Escで閉じる
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    });

    // choice を押したら「即反映」→「即閉じる」
    modal.addEventListener("click", (e) => {
      const choice = e.target.closest(".attendance-choice");
      if (!choice || !currentBtn) return;

      e.preventDefault();
      e.stopPropagation();

      const attendance = (choice.dataset.attendance || "").trim() || "maybe";
      currentBtn.dataset.attendance = attendance;

      // ボタン表示を更新（event.js と同じ見た目）
      let html = `<span class="attendance-icon attendance-maybe">?</span>`;
      if (attendance === "yes") html = `<span class="attendance-icon attendance-yes">✓</span>`;
      if (attendance === "no") html = `<span class="attendance-icon attendance-no">×</span>`;
      if (attendance === "maybe") html = `<span class="attendance-icon attendance-maybe">?</span>`;
      currentBtn.innerHTML = html;

      closeModal();
    });
  })();


  // ============================================================
  // [E] settings(ダミー): チェックON/OFF（保存しない）
  // ============================================================
  (function initDummyChecks() {
    const table = document.getElementById("participants-table");
    if (!table) return;
    if (table.dataset.mode !== "club_settings_dummy") return;

    table.addEventListener("click", (e) => {
      const btn = e.target.closest(".toggle-check");
      if (!btn) return;

      const icon = btn.querySelector(".check-icon");
      if (!icon) return;

      const willOn = icon.classList.contains("check-off");
      icon.classList.toggle("check-on", willOn);
      icon.classList.toggle("check-off", !willOn);
      if (willOn) icon.textContent = "✓";
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

    // 名前変更（クリック→モーダル）
    (function initMemberRenameModal() {
      const modal = document.getElementById("member-rename-modal");
      const closeBtn = document.getElementById("close-member-rename-modal");
      const form = document.getElementById("member-rename-form");
      const input = document.getElementById("member-rename-input");
      const hiddenId = document.getElementById("member-rename-member-id");

      if (!table || !modal || !form || !input || !hiddenId) return;

      let currentNameEl = null;

      function openModal(memberId, currentName, nameEl) {
        currentNameEl = nameEl || null;
        hiddenId.value = memberId || "";
        input.value = currentName || "";
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        setTimeout(() => input.focus(), 0);
      }

      function closeModal() {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        hiddenId.value = "";
        currentNameEl = null;
      }

      closeBtn?.addEventListener("click", (e) => {
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

      // 「名前セル」クリックで開く
      table.addEventListener("click", (e) => {
        const nameEl = e.target.closest(".member-name");
        if (!nameEl) return;

        const tr = nameEl.closest("tr[data-member-id]");
        if (!tr) return;

        e.preventDefault();
        e.stopPropagation();

        const memberId = (tr.dataset.memberId || "").trim();
        const cur = (nameEl.textContent || "").trim();

        if (!memberId) return;
        openModal(memberId, cur, nameEl);
      });

      // 保存
      form.addEventListener("submit", async (e) => {
        e.preventDefault();

        const memberId = (hiddenId.value || "").trim();
        const newName = (input.value || "").trim();

        if (!memberId) return;
        if (!newName) {
          UI.showMessage("メンバー名を入力してください。", 2400);
          return;
        }

        const fd = new FormData();
        fd.append("club_id", clubId);
        fd.append("admin_token", adminToken);
        fd.append("member_id", memberId);
        fd.append("display_name", newName);

        try {
          const data = await post(renameUrl, fd);
          if (!data.ok) {
            UI.showMessage("変更に失敗しました。", 2600);
            return;
          }

          if (currentNameEl) currentNameEl.textContent = data.display_name || newName;

          closeModal();
          UI.showMessage("メンバー名を更新しました。", 1800);
        } catch (err) {
          console.error(err);
          UI.showMessage("変更に失敗しました（ネットワーク）。", 2600);
        }
      });
    })();


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

      // UI反映
      btn.classList.toggle("is-on", next);
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", next);
        icon.classList.toggle("check-off", !next);
      }
    });
  })();


});
