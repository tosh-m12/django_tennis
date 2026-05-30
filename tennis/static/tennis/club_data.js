// tennis/static/tennis/club_data.js
// データ集計表ページ：タブ切替＋ドロップダウンによる表の選択表示
(function () {
  "use strict";

  // ---- タブ切替 ----
  const tabs = document.querySelectorAll(".data-tab");
  const panels = document.querySelectorAll(".data-tab-panel");

  function activateTab(name) {
    tabs.forEach((t) => {
      t.classList.toggle("is-active", t.dataset.tab === name);
      t.setAttribute("aria-selected", t.dataset.tab === name ? "true" : "false");
    });
    panels.forEach((p) => {
      if (p.dataset.panel === name) p.removeAttribute("hidden");
      else p.setAttribute("hidden", "");
    });
  }

  tabs.forEach((t) => {
    t.addEventListener("click", () => activateTab(t.dataset.tab));
  });

  // ---- ドロップダウン：共通フラグ ----
  const clubFlagSelect = document.getElementById("club-flag-select");
  if (clubFlagSelect) {
    const showClubFlag = (flagId) => {
      document.querySelectorAll(".club-flag-table").forEach((el) => {
        if (el.dataset.flagId === String(flagId)) el.removeAttribute("hidden");
        else el.setAttribute("hidden", "");
      });
    };
    clubFlagSelect.addEventListener("change", (e) => showClubFlag(e.target.value));
    // 初期：select の選択値（先頭）に合わせる
    if (clubFlagSelect.value) showClubFlag(clubFlagSelect.value);
  }

  // ---- ドロップダウン：固有フラグ（イベント単位） ----
  const eventFlagSelect = document.getElementById("event-flag-select");
  if (eventFlagSelect) {
    const showEventFlagBlock = (eventId) => {
      document.querySelectorAll(".event-flag-block").forEach((el) => {
        if (el.dataset.eventId === String(eventId)) el.removeAttribute("hidden");
        else el.setAttribute("hidden", "");
      });
    };
    eventFlagSelect.addEventListener("change", (e) => showEventFlagBlock(e.target.value));
    if (eventFlagSelect.value) showEventFlagBlock(eventFlagSelect.value);
  }
})();
