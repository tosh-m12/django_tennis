// tennis/static/tennis/member_detail.js
// メンバー個人ページ：名前編集の送信＋削除（幹事モードのみ）
(function () {
  "use strict";

  function getCsrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? (meta.getAttribute("content") || "") : "";
  }

  const page = document.querySelector(".member-page");
  if (!page) return;

  const csrftoken = getCsrf();
  const clubId = (page.dataset.clubId || "").trim();
  const memberId = (page.dataset.memberId || "").trim();
  const updateUrl = (page.dataset.updateUrl || "").trim();
  const deleteUrl = (page.dataset.deleteUrl || "").trim();
  const adminToken = (page.dataset.adminToken || "").trim();
  const homeUrl = (page.dataset.homeUrl || "/").trim();

  // ---- 名前保存 ----
  const form = document.getElementById("member-name-form");
  const input = document.getElementById("member-name-input");
  const nameDisplay = document.getElementById("member-name-display");

  if (form && input) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const newName = (input.value || "").trim();
      if (!newName) {
        alert("名前を入力してください。");
        input.focus();
        return;
      }

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("member_id", memberId);
      fd.append("display_name", newName);

      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;

      try {
        const r = await fetch(updateUrl, {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) throw new Error("not ok");
        // 画面に反映
        if (nameDisplay) nameDisplay.textContent = data.display_name || newName;
        document.title = (data.display_name || newName) + document.title.replace(/^[^-]+/, "");
      } catch (err) {
        console.error(err);
        alert("名前の更新に失敗しました。");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // ---- 削除（幹事モードのみ） ----
  const deleteBtn = document.getElementById("member-delete-btn");
  if (deleteBtn && deleteUrl && adminToken) {
    deleteBtn.addEventListener("click", async () => {
      if (!confirm("このメンバーを削除します。よろしいですか？")) return;

      const fd = new FormData();
      fd.append("club_id", clubId);
      fd.append("member_id", memberId);
      fd.append("admin_token", adminToken);

      deleteBtn.disabled = true;
      try {
        const r = await fetch(deleteUrl, {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) {
          alert("削除に失敗しました。" + (data.error ? "（" + data.error + "）" : ""));
          deleteBtn.disabled = false;
          return;
        }
        // 削除後はクラブホーム（幹事）へ
        window.location.href = homeUrl;
      } catch (err) {
        console.error(err);
        alert("削除に失敗しました（ネットワーク）。");
        deleteBtn.disabled = false;
      }
    });
  }
})();
