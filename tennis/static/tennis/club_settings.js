// tennis/static/tennis/club_settings.js

// ============================================================
// [UTIL] CSRF cookie 取得（Django公式パターン）
// ============================================================
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}

document.addEventListener("DOMContentLoaded", () => {
  const csrftoken = getCookie("csrftoken");


  (function initClubRenameModal() {
    const hooks = document.getElementById("club-rename-hooks");
    const nameDisplay = document.getElementById("club-name-display");

    const modal = document.getElementById("club-rename-modal");
    const closeBtn = document.getElementById("club-rename-modal-close");
    const form = document.getElementById("club-rename-modal-form");
    const input = document.getElementById("club-rename-input");

    const msgModal = document.getElementById("ui-message-modal");
    const msgBody = document.getElementById("ui-message-body");

    if (!hooks || !nameDisplay || !modal || !form || !input || !msgModal) return;

    const csrftoken = getCookie("csrftoken");
    const renameUrl = hooks.dataset.renameUrl;
    const clubId = hooks.dataset.clubId;

    let autoCloseTimer = null;

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


    // クリックで開く
    nameDisplay.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openRenameModal();
    });

    closeBtn?.addEventListener("click", closeRenameModal);

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeRenameModal();
    });

    msgModal.addEventListener("click", (e) => {
      if (e.target === msgModal) {
        msgModal.classList.remove("is-open");
        msgModal.setAttribute("aria-hidden", "true");
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const name = (input.value || "").trim();
      if (!name) {
        UI.showMessage("クラブ名を入力してください。", 2400);
        return;
      }

      const fd = new FormData();
      fd.append("club_id", clubId);
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
  // ============================================================
  (function initFlagsAddDelete() {
    const addBtn = document.getElementById("club-add-flag-btn");
    const delBtn = document.getElementById("club-delete-flag-btn");

    // 追加
    if (addBtn) {
      addBtn.addEventListener("click", async () => {
        if (addBtn.disabled) return;

        const clubId = addBtn.dataset.clubId;
        const url = addBtn.dataset.addFlagUrl;
        if (!clubId || !url) return;

        const fd = new FormData();
        fd.append("club_id", clubId);

        try {
          const r = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));

          if (!r.ok || data.error) {
            if (data.error === "max_reached") {
              alert("フラグは最大 " + data.max + " 個までです。");
              addBtn.disabled = true;
            } else {
              alert("フラグ追加に失敗しました: " + (data.error || "unknown"));
            }
            return;
          }

          window.location.reload();
        } catch (err) {
          console.error(err);
          alert("フラグ追加に失敗しました（ネットワークエラー）");
        }
      });
    }

    // 削除
    if (delBtn) {
      delBtn.addEventListener("click", () => {
        if (delBtn.disabled) return;

        UI.confirm("最後に追加したフラグを削除します。よろしいですか？", {
          okText: "削除",
          onOk: async () => {
            const clubId = delBtn.dataset.clubId;
            const url = delBtn.dataset.deleteFlagUrl;
            if (!clubId || !url) return;

            const fd = new FormData();
            fd.append("club_id", clubId);

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
  // [C] フラグ名称変更（保存あり）: ヘッダークリック→prompt
  //   - settings.html 側で th.flag-header に data-flag-id が必要
  // ============================================================
  (function initFlagRename() {
    const table = document.getElementById("participants-table");
    if (!table) return;

    const renameUrl = table.dataset.renameFlagUrl;
    if (!renameUrl) return;

    const headers = table.querySelectorAll(".flag-header[data-flag-id]");

    headers.forEach((th) => {
      th.addEventListener("click", async () => {
        const flagId = th.dataset.flagId;
        if (!flagId) return;

        const span = th.querySelector(".flag-name");
        const currentName = span ? span.textContent.trim() : "";
        const newName = window.prompt("フラグ名を入力してください", currentName);
        if (newName === null) return;

        const name = newName.trim();
        if (!name) return;

        const fd = new FormData();
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
            alert("フラグ名の変更に失敗しました: " + (data.error || "unknown"));
            return;
          }

          if (span) span.textContent = data.name || name;
        } catch (err) {
          console.error(err);
          alert("フラグ名の変更に失敗しました（ネットワークエラー）");
        }
      });
    });
  })();

  // ============================================================
  // [D] settings(ダミー): 出欠モーダル（保存しない）
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
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      currentBtn = null;
    }

    // 出欠ボタン → モーダル（table内に限定）
    table.addEventListener("click", (e) => {
      const btn = e.target.closest(".attendance-btn");
      if (!btn) return;
      openModal(btn);
    });

    closeBtn?.addEventListener("click", closeModal);

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    modal.addEventListener("click", (e) => {
      const choice = e.target.closest(".attendance-choice");
      if (!choice || !currentBtn) return;

      const v = choice.dataset.attendance; // yes/no/maybe
      currentBtn.dataset.attendance = v;

      const icon = currentBtn.querySelector(".attendance-icon");
      if (!icon) return;

      icon.classList.remove("attendance-yes", "attendance-no", "attendance-maybe");

      if (v === "yes") {
        icon.textContent = "✓";
        icon.classList.add("attendance-yes");
      } else if (v === "no") {
        icon.textContent = "×";
        icon.classList.add("attendance-no");
      } else {
        icon.textContent = "?";
        icon.classList.add("attendance-maybe");
      }

      closeModal();
    });
  })();


  // ============================================================
  // [E] settings(ダミー): 「赤チェック」ON/OFF（保存しない）
  //   - settings.html のダミーは class="toggle-check" を使ってるのでそれを拾う
  //   - event_admin でも toggle-check を使うが、あちらは admin.js が担当
  //   - ここでは data-mode="club_settings_dummy" の時だけ反応させる
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

      const willOn = icon.classList.contains("check-off"); // off→on
      icon.classList.toggle("check-on", willOn);
      icon.classList.toggle("check-off", !willOn);
      if (willOn) icon.textContent = "✓";
    });
  })();

});

