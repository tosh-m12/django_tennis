// tennis/static/tennis/topbar_hamburger.js
// 狭幅時のみ表示されるハンバーガーボタンで topbar-actions の展開/折りたたみを行う。
// （CSS で狭幅でだけハンバーガーを表示・通常時は非表示にしている）

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("topbar-hamburger");
  const menu = document.getElementById("topbar-actions");
  if (!btn || !menu) return;

  function close() {
    menu.classList.remove("is-open");
    btn.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
  }

  function open() {
    menu.classList.add("is-open");
    btn.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
  }

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (menu.classList.contains("is-open")) {
      close();
    } else {
      open();
    }
  });

  // メニュー内のリンクをタップしたら閉じる
  menu.addEventListener("click", (e) => {
    if (e.target.closest("a")) close();
  });

  // 外側タップで閉じる
  document.addEventListener("click", (e) => {
    if (!menu.classList.contains("is-open")) return;
    if (e.target.closest("#topbar-actions") || e.target.closest("#topbar-hamburger")) return;
    close();
  });

  // Escape で閉じる
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });

  // ウィンドウを広げたら自動で閉じる（インラインメニューに復帰）
  const mq = window.matchMedia("(min-width: 721px)");
  mq.addEventListener("change", (ev) => {
    if (ev.matches) close();
  });
});
