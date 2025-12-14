// tennis/static/tennis/admin.js
// v1-A++: チェック保存→自動再生成 + モーダル開閉 + ピル同期 + 公開ボタン同期 + notice同期 + schedule_json更新

document.addEventListener("DOMContentLoaded", () => {
  const table = document.getElementById("participants-table");
  const matchForm = document.getElementById("match-settings-form");
  const modal = document.getElementById("match-settings-modal");
  if (!table) return;

  const urlUpdate = table.dataset.updateParticipationUrl; // data-update-participation-url
  const urlGenerate = matchForm?.dataset.generateUrl;     // data-generate-url

  const csrftoken = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrftoken="))
    ?.split("=")[1];

  if (!urlUpdate) {
    console.error("participants-table に data-update-participation-url がありません");
    return;
  }

  // -----------------------------
  // 再生成（draft保存 + 部分HTML差し替え + UI同期）
  // -----------------------------
  function regenerate() {
    if (!urlGenerate) {
      console.warn("match-settings-form に data-generate-url がありません（再生成スキップ）");
      return;
    }

    const fd = new FormData();
    fd.append("game_type", document.getElementById("id_game_type")?.value || "doubles");
    fd.append("num_courts", document.getElementById("id_num_courts")?.value || "1");
    fd.append("num_rounds", document.getElementById("id_num_rounds")?.value || "10");

    fetch(urlGenerate, {
      method: "POST",
      headers: { "X-CSRFToken": csrftoken },
      body: fd,
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          alert("対戦表の再生成に失敗しました: " + data.error);
          return;
        }

        // ① HTML差し替え
        if (typeof data.schedule_html === "string") {
          const el = document.getElementById("schedule-area");
          if (el) el.innerHTML = data.schedule_html;
        }
        if (typeof data.stats_html === "string") {
          const el = document.getElementById("stats-area");
          if (el) el.innerHTML = data.stats_html;
        }

        // ② 人数ピル（バー側）
        const pillMatch = document.getElementById("pill-match-count");
        if (pillMatch && data.match_count != null) {
          pillMatch.textContent = data.match_count + " 人";
        }

        // ③ モーダル内人数
        const modalCount = document.querySelector("#match-settings-modal .count-pill");
        if (modalCount && data.match_count != null) {
          modalCount.textContent = data.match_count;
        }

        // ④ 種別ピル
        const pillGame = document.getElementById("pill-game-type");
        if (pillGame && data.game_type) {
          pillGame.classList.remove("pill-singles", "pill-doubles");
          if (data.game_type === "singles") {
            pillGame.classList.add("pill-singles");
            pillGame.textContent = "シングルス";
          } else {
            pillGame.classList.add("pill-doubles");
            pillGame.textContent = "ダブルス";
          }
        }

        // ⑤ 面数ピル
        const pillCourts = document.getElementById("pill-num-courts");
        if (pillCourts && data.num_courts != null) {
          pillCourts.textContent = data.num_courts + " 面";
        }

        // ⑥ ラウンド数ピル
        const pillRounds = document.getElementById("pill-num-rounds");
        if (pillRounds && data.num_rounds != null) {
          pillRounds.textContent = data.num_rounds + " ラウンド";
        }

        // ⑦ 入力（サーバーで正規化された値で戻す）
        const inCourts = document.getElementById("id_num_courts");
        if (inCourts && data.num_courts != null) inCourts.value = data.num_courts;

        const inRounds = document.getElementById("id_num_rounds");
        if (inRounds && data.num_rounds != null) inRounds.value = data.num_rounds;

        const inGT = document.getElementById("id_game_type");
        if (inGT && data.game_type) inGT.value = data.game_type;

        // ⑧ schedule_json を最新へ（公開時に送る）
        const scriptTag = document.getElementById("current-schedule-json");
        if (scriptTag && typeof data.schedule_json !== "undefined") {
          // type="application/json" の中身を更新
          scriptTag.textContent = data.schedule_json ? data.schedule_json : "null";
        }

        // ⑨ 公開ボタン同期（ここは1回だけ）
        const publishBtn = document.getElementById("publish-pill");
        if (publishBtn) {
          const state = data.publish_state || "no_schedule";
          publishBtn.dataset.publishState = state;

          publishBtn.classList.remove("pill-disabled");
          publishBtn.disabled = false;

          if (state === "no_schedule") {
            publishBtn.textContent = "📢 対戦表を公開";
            publishBtn.disabled = true;
            publishBtn.classList.add("pill-disabled");
          } else if (state === "published") {
            publishBtn.textContent = "公開済み";
            publishBtn.disabled = true;
            publishBtn.classList.add("pill-disabled");
          } else if (state === "changed") {
            publishBtn.textContent = "再公開";
          } else {
            // ready
            publishBtn.textContent = "📢 対戦表を公開";
          }
        }

        // ⑩ 注意文（changed の時だけ）
        const bar = document.querySelector(".match-settings-bar");
        let notice = document.getElementById("publish-notice");

        if (data.publish_state === "changed") {
          if (!notice && bar) {
            notice = document.createElement("div");
            notice.id = "publish-notice";
            notice.className = "publish-notice";
            notice.textContent =
              "対戦表が更新されました。この変更を参加者ページへ適用する場合は「再公開」ボタンを押してください。";
            bar.insertAdjacentElement("afterend", notice);
          }
        } else {
          if (notice) notice.remove();
        }
      })
      .catch(() => alert("対戦表の再生成に失敗しました（ネットワークエラー）"));
  }

  // -----------------------------
  // チェック変更 → DB保存 → 再生成
  // -----------------------------
  table.querySelectorAll(".match-flag-checkbox").forEach((cb) => {
    cb.addEventListener("change", () => {
      const fd = new FormData();
      fd.append("participant_id", cb.dataset.participantId);
      fd.append("checked", cb.checked ? "true" : "false");

      fetch(urlUpdate, {
        method: "POST",
        headers: { "X-CSRFToken": csrftoken },
        body: fd,
      })
        .then((r) => {
          if (!r.ok) throw new Error();
          regenerate();
        })
        .catch(() => alert("チェック保存に失敗しました"));
    });
  });

  // -----------------------------
  // モーダル：開く/閉じる
  // -----------------------------
  if (modal) {
    const triggers = document.querySelectorAll(".settings-trigger");
    const closeBtn = document.getElementById("close-settings-modal");

    const openModal = () => {
      // 現在チェックされてる人数を表示
      const modalCount = document.querySelector("#match-settings-modal .count-pill");
      if (modalCount) {
        let matchCount = 0;
        table.querySelectorAll(".match-flag-checkbox").forEach((cb) => {
          if (cb.checked) matchCount += 1;
        });
        modalCount.textContent = matchCount;
      }

      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    };

    const closeModal = () => {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
    };

    triggers.forEach((btn) => btn.addEventListener("click", openModal));
    if (closeBtn) closeBtn.addEventListener("click", closeModal);

    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    });
  }

  // -----------------------------
  // モーダルの「条件を変更する」 → 再生成 → 閉じる
  // -----------------------------
  if (matchForm) {
    matchForm.addEventListener("submit", (e) => {
      e.preventDefault();
      regenerate();

      if (modal) {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
      }
    });
  }

  // -----------------------------
  // モーダル内UI（modalがある時だけ）
  // -----------------------------
  if (modal) {
    // シングルス/ダブルス切替（hiddenに反映）
    const gameTypeInput = document.getElementById("id_game_type");
    const toggleBtns = modal.querySelectorAll(".toggle-btn");

    toggleBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const gt = btn.dataset.gameType || "doubles";
        if (gameTypeInput) gameTypeInput.value = gt;
      });
    });

    // ＋／－ステッパー
    modal.querySelectorAll(".stepper-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetId = btn.dataset.target; // "num_courts" or "num_rounds"
        const step = parseInt(btn.dataset.step || "1", 10);
        const input = document.getElementById("id_" + targetId);
        if (!input) return;

        let val = parseInt(input.value || "0", 10);

        if (targetId === "num_rounds") {
          val += step;
          if (val < 1) val = 1;
          if (val > 20) val = 20;
          input.value = val;
          return;
        }

        if (targetId === "num_courts") {
          let matchCount = 0;
          table.querySelectorAll(".match-flag-checkbox").forEach((cb) => {
            if (cb.checked) matchCount += 1;
          });

          const gt = gameTypeInput?.value || "doubles";
          const perCourt = gt === "singles" ? 2 : 4;

          let maxCourts = 8;
          if (matchCount > 0) {
            maxCourts = Math.max(1, Math.floor(matchCount / perCourt));
          }

          val += step;
          if (val < 1) val = 1;
          if (val > maxCourts) val = maxCourts;
          input.value = val;
        }
      });
    });
  }
});

// =============================
// 公開ボタン
// =============================
window.publishSchedule = function () {
  const btn = document.getElementById("publish-pill");
  if (!btn) return;

  const state = btn.dataset.publishState;
  if (state === "no_schedule" || state === "published") return;

  const scriptTag = document.getElementById("current-schedule-json");
  if (!scriptTag) {
    alert("公開用データが見つかりません（current-schedule-json がありません）");
    return;
  }

  const eventId = scriptTag.dataset.eventId;
  const publishUrl = scriptTag.dataset.publishUrl;
  const scheduleJsonText = (scriptTag.textContent || "").trim();

  const csrftoken = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrftoken="))
    ?.split("=")[1];

  const fd = new FormData();
  fd.append("event_id", eventId);

  // schedule_json が取れれば送る。取れなくても views 側が draft を publish できるのでOK。
  if (scheduleJsonText && scheduleJsonText !== "null") {
    fd.append("schedule_json", scheduleJsonText);
  }

  fetch(publishUrl, {
    method: "POST",
    headers: { "X-CSRFToken": csrftoken },
    body: fd,
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        alert("公開に失敗しました: " + data.error);
        return;
      }

      btn.dataset.publishState = "published";
      btn.textContent = "公開済み";
      btn.disabled = true;
      btn.classList.add("pill-disabled");

      const notice = document.getElementById("publish-notice");
      if (notice) notice.remove();

      alert("対戦表を公開しました。");
    })
    .catch(() => alert("公開に失敗しました（ネットワークエラー）"));
};
