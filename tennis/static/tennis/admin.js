// tennis/static/tennis/admin.js


window.hasShownChangedNotice = false;

// ============================================================
// [UTIL] CSRF cookie 取得（Django公式パターン）
// ============================================================
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop().split(";").shift();
    }
    return null;
}

document.addEventListener("DOMContentLoaded", () => {
    const csrftoken = getCookie("csrftoken");

    const participantsTable = document.getElementById("participants-table");
    const matchForm = document.getElementById("match-settings-form");

    // ============================================================
    // [BLOCK-0] 出席者リスト → 「試合参加」ON の参加者IDを集める
    //  - 対戦表の再生成に使う（AJAX）
    // ============================================================
    function collectParticipantIds() {
        if (!participantsTable) return [];
        const btns = participantsTable.querySelectorAll('.toggle-check[data-kind="match"]');
        const ids = [];
        btns.forEach((b) => {
            if (b.classList.contains("is-on")) {
                ids.push(b.dataset.participantId);
            }
        });
        return ids;
    }

    // ============================================================
    // [BLOCK-0b] 出席者リスト → 「試合参加」ON の人数を数える
    //  - 面数上限や人数ピル表示に使う
    // ============================================================
    function getMatchCountFromCheckboxes() {
        if (!participantsTable) return 0;
        let c = 0;
        participantsTable.querySelectorAll('.toggle-check[data-kind="match"]').forEach((b) => {
            if (b.classList.contains("is-on")) c += 1;
        });
        return c;
    }

    // ============================================================
    // [BLOCK-1] 条件モーダル → 面数 input の max を「現在の人数」から再計算
    // ============================================================
    function syncCourtsLimitByCurrentState() {
        const input = document.getElementById("id_num_courts");
        if (!input) return;

        const gameTypeInput = document.getElementById("id_game_type");
        const gt = gameTypeInput ? gameTypeInput.value : "doubles";

        // ★未定義だった getMatchCountFromButtons() を廃止して統一
        const matchCount = getMatchCountFromCheckboxes();

        const perCourt = gt === "singles" ? 2 : 4;

        let maxCourts = 1;
        if (matchCount >= perCourt) {
            maxCourts = Math.max(1, Math.floor(matchCount / perCourt));
        }
        if (matchCount === 0) maxCourts = 1;

        input.max = String(maxCourts);

        // 現在値が上限超えなら丸める
        let v = parseInt(input.value || "1", 10) || 1;
        if (v < 1) v = 1;
        if (v > maxCourts) v = maxCourts;
        input.value = String(v);
    }

    // ============================================================
    // [BLOCK-2] 出席者リスト → コメント保存（blur保存＋軽い連打防止）
    // ============================================================
    if (participantsTable) {
        const updateCommentUrl = participantsTable.dataset.updateCommentUrl;
        const commentDivs = participantsTable.querySelectorAll(".comment-editable");

        commentDivs.forEach((div) => {
            let timer = null;
            let lastSent = null;

            const post = () => {
                if (!updateCommentUrl) return;

                const participantId = div.dataset.participantId;
                const comment = (div.textContent || "").trim();

                const key = `${participantId}:${comment}`;
                if (key === lastSent) return;
                lastSent = key;

                const fd = new FormData();
                fd.append("participant_id", participantId);
                fd.append("comment", comment);

                fetch(updateCommentUrl, {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                .then((r) => r.json())
                .then((data) => {
                    if (!data.ok) lastSent = null;
                })
                .catch(() => {
                    lastSent = null;
                });
            };

            div.addEventListener("blur", post);

            div.addEventListener("input", () => {
                if (timer) clearTimeout(timer);
                timer = setTimeout(post, 600);
            });
        });
    }

    // ============================================================
    // [BLOCK-3] 対戦表 → AJAX で再生成（人数/面数/ラウンド/種別）
    // ============================================================
    function ajaxGenerateSchedule() {
        if (!matchForm) return;

        const url = matchForm.dataset.generateUrl;
        if (!url) {
            console.error("match-settings-form に data-generate-url がありません");
            return;
        }

        const fd = new FormData();

        // 参加者ID（カンマ区切り）
        const ids = collectParticipantIds();
        fd.append("participant_ids", ids.join(","));

        // 条件
        const gameTypeInput = document.getElementById("id_game_type");
        const numCourtsInput = document.getElementById("id_num_courts");
        const numRoundsInput = document.getElementById("id_num_rounds");

        fd.append("game_type", gameTypeInput ? gameTypeInput.value : "doubles");
        fd.append("num_courts", numCourtsInput ? numCourtsInput.value : "1");
        fd.append("num_rounds", numRoundsInput ? numRoundsInput.value : "10");

        fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: fd,
        })
        .then((r) => r.json())
        .then((data) => {
            if (data.error) {
                console.error("ajax_generate_schedule error:", data.error);
                UI.showMessage("対戦表の再生成に失敗しました: " + data.error);
                return;
            }

            // 対戦表・サマリーを差し替え
            const scheduleArea = document.getElementById("schedule-area");
            const statsArea = document.getElementById("stats-area");
            if (scheduleArea && typeof data.schedule_html === "string") {
                scheduleArea.innerHTML = data.schedule_html;
            }
            if (statsArea && typeof data.stats_html === "string") {
                statsArea.innerHTML = data.stats_html;
            }

            // ===== 条件バーの 4 つのピルを更新 =====
            const pillGameType = document.getElementById("pill-game-type");
            const pillNumCourts = document.getElementById("pill-num-courts");
            const pillMatchCount = document.getElementById("pill-match-count");
            const pillNumRounds = document.getElementById("pill-num-rounds");

            if (pillGameType && data.game_type) {
                pillGameType.classList.remove("pill-singles", "pill-doubles");
                if (data.game_type === "singles") {
                    pillGameType.classList.add("pill-singles");
                    pillGameType.textContent = "シングルス";
                } else {
                    pillGameType.classList.add("pill-doubles");
                    pillGameType.textContent = "ダブルス";
                }
            }

            if (pillNumCourts && typeof data.num_courts !== "undefined") {
                pillNumCourts.textContent = data.num_courts + " 面";
            }

            if (pillMatchCount && typeof data.match_count !== "undefined") {
                pillMatchCount.textContent = data.match_count + " 人";
            }

            // ★ モーダル内の人数ピルも同期
            const modalCountPill = document.querySelector("#match-settings-modal .count-pill");
            if (modalCountPill && typeof data.match_count !== "undefined") {
                modalCountPill.textContent = data.match_count;
            }

            // ★ モーダル内の「面数 input」も同期（value と max を更新）
            const modalNumCourtsInput = document.getElementById("id_num_courts");
            if (modalNumCourtsInput) {
                if (typeof data.num_courts !== "undefined") {
                    modalNumCourtsInput.value = data.num_courts;
                }

                const gt = data.game_type || (document.getElementById("id_game_type")?.value) || "doubles";
                const perCourt = gt === "singles" ? 2 : 4;
                const mc = (typeof data.match_count !== "undefined") ? data.match_count : 0;

                let maxCourts = 1;
                if (mc >= perCourt) {
                    maxCourts = Math.max(1, Math.floor(mc / perCourt));
                }
                if (mc === 0) maxCourts = 1;

                modalNumCourtsInput.max = String(maxCourts);

                const cur = parseInt(modalNumCourtsInput.value || "1", 10) || 1;
                if (cur > maxCourts) modalNumCourtsInput.value = String(maxCourts);
                if (cur < 1) modalNumCourtsInput.value = "1";
            }

            if (pillNumRounds && typeof data.num_rounds !== "undefined") {
                pillNumRounds.innerHTML = data.num_rounds + " ラウンド ";
            }

            // ===== 公開ボタンの状態を更新 =====
            const btn = document.getElementById("publish-pill");
            if (btn) {
                const state = data.publish_state || "no_schedule";

                if (data.publish_state === "changed" && !window.hasShownChangedNotice) {
                UI.showMessage(
                    "対戦表が更新されました。\n参加者ページへ反映するには「再公開」を押してください。",
                    4000
                );
                window.hasShownChangedNotice = true;
                }

                btn.classList.remove("pill-disabled");
                btn.disabled = false;

                btn.dataset.publishState = state;

                if (state === "no_schedule") {
                    btn.textContent = "📢 対戦表を公開";
                    btn.disabled = true;
                    btn.classList.add("pill-disabled");
                } else if (state === "published") {
                    btn.textContent = "公開済み";
                    btn.disabled = true;
                    btn.classList.add("pill-disabled");
                } else if (state === "changed") {
                    btn.textContent = "再公開";
                } else {
                    btn.textContent = "📢 対戦表を公開";
                }
            }

            // 最後に：面数の max は現状に合わせて再同期（念のため）
            syncCourtsLimitByCurrentState();
        })
        .catch((err) => {
            console.error("network error:", err);
            UI.showMessage("対戦表の再生成に失敗しました（ネットワークエラー）");
        });
    }

    // ============================================================
    // [BLOCK-4] 出席者リスト → 「試合参加」ON/OFF（settings式ボタン）
    //  - 変更したら ajaxGenerateSchedule()
    // ============================================================
    if (participantsTable) {
        participantsTable.addEventListener("click", (e) => {
            const btn = e.target.closest('.toggle-check[data-kind="match"]');
            if (!btn) return;

            const willOn = !btn.classList.contains("is-on");
            btn.classList.toggle("is-on", willOn);

            const icon = btn.querySelector(".check-icon");
            if (icon) {
                icon.classList.toggle("check-on", willOn);
                icon.classList.toggle("check-off", !willOn);
            }

            syncCourtsLimitByCurrentState();
            ajaxGenerateSchedule();
        });
    }

    // ============================================================
    // [BLOCK-5] 出席者リスト → 「クラブフラグ」ON/OFF（保存あり）
    // ============================================================
    if (participantsTable) {
        const toggleFlagUrl = participantsTable.dataset.toggleFlagUrl;

        participantsTable.addEventListener("click", (e) => {
            const btn = e.target.closest(".toggle-check");
            if (!btn) return;

            // フラグボタンだけ対象（試合参加ボタンと区別）
            const flagId = btn.dataset.flagId;
            if (!flagId) return;

            if (!toggleFlagUrl) {
                console.error("data-toggle-flag-url がありません");
                return;
            }

            const participantId = btn.dataset.participantId;
            const willOn = !btn.classList.contains("is-on");

            // ===== 見た目を先に切り替え =====
            btn.classList.toggle("is-on", willOn);

            const icon = btn.querySelector(".check-icon");
            if (icon) {
                icon.classList.toggle("check-on", willOn);
                icon.classList.toggle("check-off", !willOn);
            }

            // ===== サーバへ保存 =====
            const fd = new FormData();
            fd.append("participant_id", participantId);
            fd.append("club_flag_id", flagId);
            fd.append("checked", willOn ? "true" : "false");

            fetch(toggleFlagUrl, {
                method: "POST",
                headers: { "X-CSRFToken": getCookie("csrftoken") },
                body: fd,
            })
            .then((r) => r.json())
            .then((data) => {
                if (!data.ok) {
                    // 失敗したら見た目を戻す
                    btn.classList.toggle("is-on", !willOn);
                    if (icon) {
                        icon.classList.toggle("check-on", !willOn);
                        icon.classList.toggle("check-off", willOn);
                    }
                    UI.showMessage("フラグ更新に失敗しました");
                }
            })
            .catch(() => {
                btn.classList.toggle("is-on", !willOn);
                if (icon) {
                    icon.classList.toggle("check-on", !willOn);
                    icon.classList.toggle("check-off", willOn);
                }
                UI.showMessage("フラグ更新に失敗しました（ネットワーク）");
            });
        });
    }

    // ============================================================
    // [BLOCK-6] フラグ削除 / 追加（存在する場合だけ動かす）
    // ============================================================
    const deleteFlagBtn = document.getElementById("delete-flag-btn");
    if (deleteFlagBtn) {
    deleteFlagBtn.addEventListener("click", () => {
        const eventId = deleteFlagBtn.dataset.eventId;
        const deleteUrl = deleteFlagBtn.dataset.deleteFlagUrl;

        if (deleteFlagBtn.disabled) return;

        UI.confirm("最後に追加したフラグを削除します。よろしいですか？", {
        okText: "削除",
        onOk: async () => {
            const fd = new FormData();
            fd.append("event_id", eventId);

            try {
            const r = await fetch(deleteUrl, {
                method: "POST",
                headers: { "X-CSRFToken": getCookie("csrftoken") },
                body: fd,
            });
            const data = await r.json().catch(() => ({}));

            if (!r.ok || data.error) {
                UI.showMessage("削除できませんでした。", 2600);
                return;
            }

            deleteFlagBtn.disabled = true;
            window.location.reload();
            } catch (err) {
            console.error(err);
            UI.showMessage("削除に失敗しました（ネットワーク）。", 2600);
            }
        },
        });
    });
    }


    const addFlagBtn = document.getElementById("add-flag-btn");
    if (addFlagBtn) {
        const addFlagUrl = addFlagBtn.dataset.addFlagUrl;
        addFlagBtn.addEventListener("click", () => {
            if (addFlagBtn.disabled) return;

            const eventId = addFlagBtn.dataset.eventId;
            const fd = new FormData();
            fd.append("event_id", eventId);

            fetch(addFlagUrl, {
                method: "POST",
                headers: { "X-CSRFToken": getCookie("csrftoken") },
                body: fd,
            })
            .then((r) => r.json())
            .then((data) => {
                if (data.error) {
                if (data.error === "max_reached") {
                    UI.showMessage("フラグは最大 " + data.max + " 個までです。", 2600);
                    addFlagBtn.disabled = true;
                } else {
                    UI.showMessage("フラグ追加に失敗しました。", 2600);
                }
                return;
                }
                window.location.reload();
            })
            .catch((err) => {
                console.error("network error:", err);
                UI.showMessage("フラグ追加に失敗しました（ネットワーク）。", 2600);
            });
        });
    }

    // ============================================================
    // [BLOCK-7] 条件変更モーダルの表示制御（ここに「＋／－」がある）
    // ============================================================
    const modal = document.getElementById("match-settings-modal");

    if (modal) {
        const triggers = document.querySelectorAll(".settings-trigger");
        const closeBtn = document.getElementById("close-settings-modal");

        const openModal = () => {
            // ★ 今の試合参加人数を数えてモーダルに反映
            const countPill = modal.querySelector(".count-pill");
            if (countPill) {
                // ★未定義だった getMatchCountFromButtons() を廃止して統一
                countPill.textContent = String(getMatchCountFromCheckboxes());
            }

            syncCourtsLimitByCurrentState();

            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
        };

        const closeModal = () => {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
        };

        triggers.forEach((btn) => {
            btn.addEventListener("click", openModal);
        });

        if (closeBtn) {
            closeBtn.addEventListener("click", closeModal);
        }

        modal.addEventListener("click", (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && modal.classList.contains("is-open")) {
                closeModal();
            }
        });

        // ------------------------------------------------------------
        // [BLOCK-7a] シングルス / ダブルス トグル
        // ------------------------------------------------------------
        const toggleBtns = modal.querySelectorAll(".toggle-btn");
        const gameTypeInput = document.getElementById("id_game_type");

        if (toggleBtns.length && gameTypeInput) {
            toggleBtns.forEach((btn) => {
                btn.addEventListener("click", () => {
                    toggleBtns.forEach((b) => b.classList.remove("active"));
                    btn.classList.add("active");
                    const gt = btn.dataset.gameType;
                    if (gt) {
                        gameTypeInput.value = gt;
                    }
                    syncCourtsLimitByCurrentState();
                });
            });
        }

        // ------------------------------------------------------------
        // [BLOCK-7b] ★ここが「＋／－ ステッパー」ブロック
        // ------------------------------------------------------------
        const steppers = modal.querySelectorAll(".stepper-btn");

        steppers.forEach((btn) => {
            btn.addEventListener("click", () => {
                const targetId = btn.dataset.target;
                const step = parseInt(btn.dataset.step, 10) || 1;
                const input = document.getElementById("id_" + targetId);
                if (!input) return;

                let val = parseInt(input.value || "0", 10);

                if (targetId === "num_courts") {
                    // ★未定義だった getMatchCountFromButtons() を廃止して統一
                    const matchCount = getMatchCountFromCheckboxes();

                    const gt = (document.getElementById("id_game_type")?.value) || "doubles";
                    const perCourt = gt === "singles" ? 2 : 4;

                    let maxCourts = 1;
                    if (matchCount >= perCourt) {
                        maxCourts = Math.max(1, Math.floor(matchCount / perCourt));
                    }
                    if (matchCount === 0) maxCourts = 1;

                    val += step;
                    if (val < 1) val = 1;
                    if (val > maxCourts) val = maxCourts;
                    input.value = String(val);
                    return;
                }

                if (targetId === "num_rounds") {
                    val += step;
                    if (val < 1) val = 1;
                    if (val > 20) val = 20;
                    input.value = String(val);
                }
            });
        });

        // ------------------------------------------------------------
        // [BLOCK-7c] フォーム submit → AJAX だけ動かす
        // ------------------------------------------------------------
        if (matchForm) {
            matchForm.addEventListener("submit", (e) => {
                e.preventDefault();
                ajaxGenerateSchedule();
                closeModal();
            });
        }
    }

    // ============================================================
    // [BLOCK-8] スコア入力（クリックで編集 → API保存）
    // ============================================================
    const scheduleArea = document.getElementById("schedule-area");

    if (scheduleArea) {
        scheduleArea.addEventListener("click", (e) => {
            const scoreSpan = e.target.closest(".tb-score");
            if (!scoreSpan) return;

            if (scoreSpan.dataset.editing === "1") return;
            scoreSpan.dataset.editing = "1";

            const currentText = scoreSpan.textContent.trim();
            const currentValue = currentText === "-" ? "" : currentText;

            const saveUrl = scoreSpan.dataset.saveUrl;
            const matchId = scoreSpan.dataset.matchId;
            const side = scoreSpan.dataset.side;

            if (!matchId) {
                UI.showMessage("この対戦表は未公開（または変更中）です。スコア登録は公開後にできます。");
                scoreSpan.removeAttribute("data-editing");
                scoreSpan.textContent = (currentValue === "" ? "-" : currentValue);
                return;
            }

            const input = document.createElement("input");
            input.type = "number";
            input.className = "tb-score-input";
            input.value = currentValue;

            scoreSpan.textContent = "";
            scoreSpan.appendChild(input);
            input.focus();
            input.select();

            const finishEdit = async (cancel = false) => {
                const nextVal = cancel ? currentValue : (input.value || "").trim();

                scoreSpan.removeAttribute("data-editing");
                scoreSpan.textContent = (nextVal === "" ? "-" : nextVal);

                if (cancel) return;

                try {
                    const fd = new FormData();
                    fd.append("match_id", matchId);
                    fd.append("side", side);
                    fd.append("value", nextVal);

                    const r = await fetch(saveUrl, {
                        method: "POST",
                        headers: { "X-CSRFToken": getCookie("csrftoken") },
                        body: fd,
                    });
                    const data = await r.json().catch(() => ({}));

                    if (!r.ok || !data.ok) {
                        UI.showMessage("スコア保存に失敗しました");
                        console.error(data);
                        scoreSpan.textContent = (currentValue === "" ? "-" : currentValue);
                    }
                } catch (err) {
                    console.error(err);
                    UI.showMessage("スコア保存に失敗しました（ネットワーク）");
                    scoreSpan.textContent = (currentValue === "" ? "-" : currentValue);
                }
            };

            input.addEventListener("blur", () => finishEdit(false));
            input.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter") {
                    ev.preventDefault();
                    input.blur();
                } else if (ev.key === "Escape") {
                    ev.preventDefault();
                    finishEdit(true);
                }
            });
        });
    }
});

// ============================================================
// [GLOBAL] 対戦表公開ボタン（window に出す）
//  - UI は ui_modal.js が提供（UI.confirm / UI.showMessage）
//  - 成功メッセージは1回だけ
// ============================================================
window.publishSchedule = function () {
  const btn = document.getElementById("publish-pill");
  if (!btn) return;

  // UI が読み込まれていない場合の安全策
  if (typeof window.UI === "undefined") {
    console.error("UI is not defined. ui_modal.js が admin.js より先に読み込まれているか確認してください。");
    alert("UI が読み込まれていません（ui_modal.js）。");
    return;
  }

  const state = btn.dataset.publishState;
  if (state === "no_schedule") {
    UI.showMessage("対戦表がまだ生成されていません。", 2600);
    return;
  }
  if (state === "published") return;

  const scriptTag = document.getElementById("current-schedule-json");
  if (!scriptTag) {
    UI.showMessage("対戦表がまだ生成されていません。", 2600);
    return;
  }

  const eventId = scriptTag.dataset.eventId;
  const publishUrl = scriptTag.dataset.publishUrl;
  const scheduleJson = (scriptTag.textContent || "").trim();

  if (!eventId || !publishUrl || !scheduleJson) {
    UI.showMessage("公開に必要な情報が不足しています。", 2600);
    return;
  }

  const postPublish = async (force) => {
    const fd = new FormData();
    fd.append("event_id", eventId);
    fd.append("schedule_json", scheduleJson);
    if (force) fd.append("force", "1");

    const r = await fetch(publishUrl, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      body: fd,
    });

    const data = await r.json().catch(() => ({}));
    return { r, data };
  };

  // ★ UI更新だけ担当（showMessageはここでは出さない）
  const applyPublishedUI = () => {
    btn.dataset.publishState = "published";
    btn.textContent = "公開済み";
    btn.classList.add("pill-disabled");
    btn.disabled = true;

    // 「changed notice」を一回だけ出す制御をリセットしたいならここ
    if (typeof window.hasShownChangedNotice !== "undefined") {
      window.hasShownChangedNotice = false;
    }
  };

  (async () => {
    try {
      let { r, data } = await postPublish(false);

      // スコアが既にある → confirm で上書き公開
      if (r.status === 409 && data && data.error === "score_exists") {
        UI.confirm(data.message || "スコアが存在します。上書き公開しますか？", {
          okText: "上書き公開",
          cancelText: "中止",
          onOk: async () => {
            try {
              const res2 = await postPublish(true);
              const r2 = res2.r;
              const d2 = res2.data;

              if (!r2.ok || (d2 && d2.error)) {
                UI.showMessage("公開に失敗しました。", 2600);
                console.error(d2);
                return;
              }

              applyPublishedUI();
              UI.showMessage("対戦表を公開しました。", 2200);
            } catch (err2) {
              console.error("network error:", err2);
              UI.showMessage("公開に失敗しました（ネットワーク）。", 2600);
            }
          },
        });
        return;
      }

      // 通常エラー
      if (!r.ok || (data && data.error)) {
        UI.showMessage("公開に失敗しました。", 2600);
        console.error(data);
        return;
      }

      // 通常成功
      applyPublishedUI();
      UI.showMessage("対戦表を公開しました。", 2200);
    } catch (err) {
      console.error("network error:", err);
      UI.showMessage("公開に失敗しました（ネットワーク）。", 2600);
    }
  })();
};
