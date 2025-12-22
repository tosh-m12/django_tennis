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

    // 背景クリックで閉じる（OK以外のキャンセルボタンは作らない方針）
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
