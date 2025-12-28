// tennis/static/tennis/topbar_back.js
(function () {
  function qs(sel, root = document) {
    return root.querySelector(sel);
  }

  // 幹事 / メンバーで保存キーを分離
  function storageKey(clubToken, isAdmin) {
    return `tennis_last_calendar_${clubToken}_${isAdmin ? "admin" : "public"}`;
  }

  function readLastYM(clubToken, isAdmin) {
    try {
      const raw = sessionStorage.getItem(storageKey(clubToken, isAdmin));
      if (!raw) return null;
      const obj = JSON.parse(raw);
      const y = parseInt(obj?.year, 10);
      const m = parseInt(obj?.month, 10);
      if (!y || !m) return null;
      return { year: y, month: m };
    } catch {
      return null;
    }
  }

  function writeLastYM(clubToken, isAdmin, year, month) {
    try {
      sessionStorage.setItem(
        storageKey(clubToken, isAdmin),
        JSON.stringify({ year, month, savedAt: Date.now() })
      );
    } catch {}
  }

  function setBackLinkToMonth(backLink, homeUrl, ym) {
    const u = new URL(homeUrl, window.location.origin);
    u.searchParams.set("year", String(ym.year));
    u.searchParams.set("month", String(ym.month));
    backLink.setAttribute("href", u.toString());
  }

  document.addEventListener("DOMContentLoaded", () => {
    const hooks = qs("#page-hooks");
    const backLink = qs("#topbar-back-link");
    const settingsLink = qs("#topbar-settings-link");
    if (!hooks) return;

    const page = (hooks.dataset.page || "").trim();
    const clubToken = (hooks.dataset.clubToken || "").trim();
    const isAdmin = String(hooks.dataset.isAdmin || "0") === "1";

    /* ========= club_home ========= */
    if (page === "club_home") {
      // もどるは不要
      if (backLink) backLink.style.display = "none";

      // 表示中の年月を保存
      const y = parseInt(hooks.dataset.year || "", 10);
      const m = parseInt(hooks.dataset.month || "", 10);
      if (clubToken && y && m) {
        writeLastYM(clubToken, isAdmin, y, m);
      }
      return;
    }

    /* ========= settings ========= */
    if (page === "settings") {
      // 設定ページでは「設定」リンク不要
      if (settingsLink) settingsLink.style.display = "none";
    }

    /* ========= event / others ========= */
    if (!backLink || !clubToken) return;

    const homeUrl =
      (backLink.dataset.homeUrl || backLink.getAttribute("href") || "").trim();
    if (!homeUrl) return;

    const ym = readLastYM(clubToken, isAdmin);
    if (ym) {
      setBackLinkToMonth(backLink, homeUrl, ym);
    }
  });
})();
