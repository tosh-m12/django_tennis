// tennis/static/tennis/calendar.js
// club_home カレンダー：イベント作成モーダル（_ui_modals.html）操作
// 追加要件（B）
// - 中止イベントは「白地＋黒枠」(CSS側)
// - 一般ユーザーは中止イベントをクリックしても何も起きない（リンク無し＋JSでもガード）
// - 幹事は通常通りクリック可（リンクも出る）
// - event-card 追記はしない（作成後はリロードで反映）
// - place 対応

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}

document.addEventListener("DOMContentLoaded", () => {
  // ------------------------------------------------------------
  // Hooks / mode 判定
  // ------------------------------------------------------------
  const hooks = document.getElementById("club-calendar-hooks");
  const isAdmin = !!hooks; // 幹事ページのみ hooks が存在

  const csrftoken = getCookie("csrftoken");

  // ------------------------------------------------------------
  // ① 共通：一般ユーザーの「中止イベントは何も起きない」をJSでもガード
  //    （テンプレでリンク無しにしているが、保険）
  // ------------------------------------------------------------
  document.addEventListener("click", (e) => {
    const locked = e.target.closest(".cal-event.is-cancelled.is-public-lock");
    if (!locked) return;

    // クリックしても何も起きない（リンク遷移や親TDクリックによるモーダル発火も抑止）
    e.preventDefault();
    e.stopPropagation();
  }, true);

  // ------------------------------------------------------------
  // ② 幹事ページ以外：モーダル操作はしない（ここで終了）
  // ------------------------------------------------------------
  if (!isAdmin) return;

  // ------------------------------------------------------------
  // ③ 幹事：作成モーダル制御
  // ------------------------------------------------------------
  const modal = document.getElementById("club-event-modal");
  const closeBtn = document.getElementById("club-event-modal-close");
  const form = document.getElementById("club-event-form");
  const dateInput = document.getElementById("club-event-date");

  const titleInput = document.getElementById("club-event-title");
  const placeInput = document.getElementById("club-event-place");

  const startH = document.getElementById("club-start-hour");
  const startM = document.getElementById("club-start-min");
  const endH = document.getElementById("club-end-hour");
  const endM = document.getElementById("club-end-min");

  const hiddenStart = document.getElementById("club-event-start-time");
  const hiddenEnd = document.getElementById("club-event-end-time");

  const createUrl = (hooks?.dataset.createUrl || "").trim();
  const clubId = (hooks?.dataset.clubId || "").trim();

  // club_home（幹事）以外/部品不足では何もしない
  if (!modal || !form || !dateInput) return;

  // ===== 時刻プルダウン（00,15,30,45） =====
  function fillTimeSelects(defaultStart, defaultEnd) {
    const hh = [...Array(24)].map((_, i) => String(i).padStart(2, "0"));
    const mm = ["00", "15", "30", "45"];

    [startH, endH].forEach((sel) => {
      if (!sel) return;
      sel.innerHTML = hh.map((v) => `<option value="${v}">${v}</option>`).join("");
    });
    [startM, endM].forEach((sel) => {
      if (!sel) return;
      sel.innerHTML = mm.map((v) => `<option value="${v}">${v}</option>`).join("");
    });

    const [sH, sM] = (defaultStart || "09:00").split(":");
    const [eH, eM] = (defaultEnd || "12:00").split(":");

    if (startH) startH.value = (sH || "09");
    if (startM) startM.value = (sM || "00");
    if (endH) endH.value = (eH || "12");
    if (endM) endM.value = (eM || "00");
  }

  // select変更を hidden(start_time/end_time) に反映
  function syncHiddenTime() {
    const sh = startH?.value ?? "";
    const sm = startM?.value ?? "";
    const eh = endH?.value ?? "";
    const em = endM?.value ?? "";

    if (hiddenStart) hiddenStart.value = (sh && sm) ? `${sh}:${sm}` : "";
    if (hiddenEnd) hiddenEnd.value = (eh && em) ? `${eh}:${em}` : "";
  }

  [startH, startM, endH, endM].forEach((sel) => {
    sel?.addEventListener("change", syncHiddenTime);
  });

  function openModal(dateStr) {
    // create mode
    const mode = document.getElementById("club-event-mode");
    const eventId = document.getElementById("club-event-event-id");
    const modalTitle = document.getElementById("club-event-modal-title");

    if (mode) mode.value = "create";
    if (eventId) eventId.value = "";
    if (modalTitle) modalTitle.textContent = "イベント作成";

    // date 表示＆hidden
    dateInput.value = dateStr;
    const dateText = document.getElementById("club-event-date-text");
    if (dateText) dateText.textContent = dateStr;

    // 入力欄初期化
    if (titleInput) titleInput.value = "";
    if (placeInput) placeInput.value = "";

    fillTimeSelects("09:00", "12:00");

    // hidden にも初期反映
    if (hiddenStart) hiddenStart.value = "09:00";
    if (hiddenEnd) hiddenEnd.value = "12:00";

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");

    // if (titleInput) titleInput.focus();
  }

  function closeModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
  }

  // 背景クリックで閉じる
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
  closeBtn?.addEventListener("click", closeModal);

  // 日付セルクリック（data-date）
  document.querySelectorAll(".practice-calendar td.day-cell[data-date]").forEach((td) => {
    td.addEventListener("click", (e) => {
      // 既存イベント（カード/リンク）をクリックしたらモーダルを開かない
      if (e.target.closest(".event-card, .cal-event")) return;
      if (e.target.closest("a")) return;

      const key = td.getAttribute("data-date");
      if (!key) return;
      openModal(key);
    });
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!createUrl || !clubId) {
      alert("createUrl / clubId が取得できません（club-calendar-hooks を確認）");
      return;
    }

    const title = (titleInput?.value || "").trim();
    if (!title) {
      alert("タイトルを入力してください");
      return;
    }

    // hidden time を最新化
    syncHiddenTime();

    const fd = new FormData(form);
    fd.set("club_id", clubId);

    const submitBtn = form.querySelector('button[type="submit"]');
    const prevDisabled = submitBtn?.disabled;
    if (submitBtn) submitBtn.disabled = true;

    try {
      const r = await fetch(createUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken },
        body: fd,
      });

      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        alert("登録に失敗しました");
        console.error(data);
        return;
      }

      closeModal();

      // event-card追記はいらない → リロードで反映
      window.location.reload();
    } catch (err) {
      console.error(err);
      alert("登録に失敗しました（ネットワーク）");
    } finally {
      if (submitBtn) submitBtn.disabled = !!prevDisabled;
    }
  });

  // ============================================================
  // [SYNC] event.html 側の更新を拾ってカレンダーを更新（安全策：再読込）
  // ============================================================
  window.addEventListener("storage", (ev) => {
    if (ev.key !== "tennis_event_updated") return;
    try {
      window.location.reload();
    } catch {
      window.location.reload();
    }
  });
});
