// tennis/static/tennis/admin.js

// CSRF cookie 取得（Django公式パターン）
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

    // =============================
    // 共通：試合参加IDを集めて AJAX で対戦表を再生成
    // =============================
    function collectParticipantIds() {
        if (!participantsTable) return [];
        const cbs = participantsTable.querySelectorAll(".match-flag-checkbox");
        const ids = [];
        cbs.forEach((cb) => {
            if (cb.checked) {
                ids.push(cb.dataset.participantId);
            }
        });
        return ids;
    }

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
                "X-CSRFToken": csrftoken,
            },
            body: fd,
        })
            .then((r) => r.json())
            .then((data) => {
                if (data.error) {
                    console.error("ajax_generate_schedule error:", data.error);
                    alert("対戦表の再生成に失敗しました: " + data.error);
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

                // ★ モーダル内の人数ピルも同期させる
                const modalCountPill = document.querySelector(
                    "#match-settings-modal .count-pill"
                );
                if (modalCountPill && typeof data.match_count !== "undefined") {
                    modalCountPill.textContent = data.match_count;
                }

                if (pillNumRounds && typeof data.num_rounds !== "undefined") {
                    pillNumRounds.innerHTML =
                        data.num_rounds + " ラウンド ";
                }

                // ===== 公開ボタンの状態を更新 =====
                const btn = document.getElementById("publish-pill");
                if (btn) {
                    const state = data.publish_state || "no_schedule";

                    // まず一旦「有効」状態にクリア
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
                        // 公開済みとの差分がある → 再公開
                        btn.textContent = "再公開";
                    } else {
                        // ready
                        btn.textContent = "📢 対戦表を公開";
                    }
                }

                // ===== 注意メッセージ（publish-notice）の表示制御 =====
                const bar = document.querySelector(".match-settings-bar");
                let notice = document.getElementById("publish-notice");

                if (data.publish_state === "changed") {
                    // まだ notice が無ければ作成
                    if (!notice && bar) {
                        notice = document.createElement("div");
                        notice.id = "publish-notice";
                        notice.className = "publish-notice";
                        notice.textContent =
                            "対戦表が更新されました。この変更を参加者ページへ適用する場合は「再公開」ボタンを押してください。";
                        bar.insertAdjacentElement("afterend", notice);
                    }
                } else {
                    // changed 以外になったら notice は消す
                    if (notice) {
                        notice.remove();
                    }
                }

            })
            .catch((err) => {
                console.error("network error:", err);
                alert("対戦表の再生成に失敗しました（ネットワークエラー）");
            });    
    }

    // =============================
    // 1) 試合参加フラグの変更 → AJAX で再生成
    // =============================
    if (participantsTable) {
        const matchCheckboxes = participantsTable.querySelectorAll(".match-flag-checkbox");
        matchCheckboxes.forEach((cb) => {
            cb.addEventListener("change", () => {
                ajaxGenerateSchedule();
            });
        });
    }

    // =============================
    // 1.5) 任意フラグの追加・名称変更・ON/OFF
    // =============================
    const addFlagBtn = document.getElementById("add-flag-btn");

    if (participantsTable) {
        const toggleFlagUrl = participantsTable.dataset.toggleFlagUrl;

        // フラグチェックのON/OFF
        const flagCheckboxes = participantsTable.querySelectorAll(".flag-checkbox");
        flagCheckboxes.forEach((cb) => {
            cb.addEventListener("change", () => {
                const participantId = cb.dataset.participantId;
                const flagId = cb.dataset.flagId;
                const checked = cb.checked;

                const fd = new FormData();
                fd.append("participant_id", participantId);
                fd.append("flag_id", flagId);
                fd.append("checked", checked ? "true" : "false");

                fetch(toggleFlagUrl, {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                    .then((r) => r.json())
                    .then((data) => {
                        if (data.error) {
                            console.error("toggle_flag error:", data.error);
                            alert("フラグ更新に失敗しました: " + data.error);
                        }
                    })
                    .catch((err) => {
                        console.error("network error:", err);
                        alert("フラグ更新に失敗しました（ネットワークエラー）");
                    });
            });
        });

        // フラグ名の編集（ヘッダークリックで prompt）
        const renameFlagUrl = participantsTable.dataset.renameFlagUrl;
        const flagHeaders = participantsTable.querySelectorAll(".flag-header");
        flagHeaders.forEach((th) => {
            th.addEventListener("click", () => {
                const flagId = th.dataset.flagId;
                const span = th.querySelector(".flag-name");
                const currentName = span ? span.textContent.trim() : "";
                const newName = window.prompt("フラグ名を入力してください", currentName);
                if (newName === null) return; // キャンセル

                const fd = new FormData();
                fd.append("flag_id", flagId);
                fd.append("name", newName);

                fetch(renameFlagUrl, {
                    method: "POST",
                    headers: { "X-CSRFToken": csrftoken },
                    body: fd,
                })
                    .then((r) => r.json())
                    .then((data) => {
                        if (data.error) {
                            alert("フラグ名の変更に失敗しました: " + data.error);
                        } else if (span) {
                            span.textContent = data.name;
                        }
                    })
                    .catch((err) => {
                        console.error("network error:", err);
                        alert("フラグ名の変更に失敗しました（ネットワークエラー）");
                    });
            });
        });
    }

    // ==== フラグ削除 ====
    const deleteFlagBtn = document.getElementById("delete-flag-btn");
    if (deleteFlagBtn) {
        deleteFlagBtn.addEventListener("click", () => {
            const eventId = deleteFlagBtn.dataset.eventId;
            const deleteUrl = deleteFlagBtn.dataset.deleteFlagUrl;

            if (deleteFlagBtn.disabled) return;

            if (!confirm("最後に追加したフラグを削除します。よろしいですか？")) {
                return;
            }

            const fd = new FormData();
            fd.append("event_id", eventId);

            fetch(deleteUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrftoken },
                body: fd,
            })
                .then((r) => r.json())
                .then((data) => {
                    if (data.error) {
                        alert("削除できません: " + data.error);
                        return;
                    }

                    deleteFlagBtn.disabled = true;
                    window.location.reload();
                })
                .catch((err) => {
                    console.error(err);
                    alert("削除に失敗しました（ネットワークエラー）");
                });
        });
    }

    // フラグ追加ボタン
    if (addFlagBtn) {
        const addFlagUrl = addFlagBtn.dataset.addFlagUrl;
        addFlagBtn.addEventListener("click", () => {
            if (addFlagBtn.disabled) return;

            const eventId = addFlagBtn.dataset.eventId;
            const fd = new FormData();
            fd.append("event_id", eventId);

            fetch(addFlagUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrftoken },
                body: fd,
            })
                .then((r) => r.json())
                .then((data) => {
                    if (data.error) {
                        if (data.error === "max_reached") {
                            alert("フラグは最大 " + data.max + " 個までです。");
                            addFlagBtn.disabled = true;
                        } else {
                            alert("フラグ追加に失敗しました: " + data.error);
                        }
                        return;
                    }
                    window.location.reload();
                })
                .catch((err) => {
                    console.error("network error:", err);
                    alert("フラグ追加に失敗しました（ネットワークエラー）");
                });
        });
    }

    // =============================
    // 2) 条件変更モーダルの表示制御
    // =============================
    const modal = document.getElementById("match-settings-modal");

    if (modal) {
        const triggers = document.querySelectorAll(".settings-trigger");
        const closeBtn = document.getElementById("close-settings-modal");

        const openModal = () => {
            // ★ 今の試合参加人数を数えてモーダルに反映
            if (participantsTable) {
                let matchCount = 0;
                const matchCheckboxes =
                    participantsTable.querySelectorAll(".match-flag-checkbox");
                matchCheckboxes.forEach((cb) => {
                    if (cb.checked) matchCount += 1;
                });

                const countPill = modal.querySelector(".count-pill");
                if (countPill) {
                    countPill.textContent = matchCount;
                }
            }

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

        // シングルス / ダブルス トグル
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
                });
            });
        }

        // ＋／－ ステッパー
        const steppers = modal.querySelectorAll(".stepper-btn");

        steppers.forEach((btn) => {
            btn.addEventListener("click", () => {
                const targetId = btn.dataset.target;
                const step = parseInt(btn.dataset.step, 10) || 1;
                const input = document.getElementById("id_" + targetId);
                if (!input) return;

                let val = parseInt(input.value || "0", 10);

                if (targetId === "num_courts") {
                    // ★いまチェックされている「試合参加」人数をカウント
                    let matchCount = 0;
                    if (participantsTable) {
                        const matchCheckboxes =
                            participantsTable.querySelectorAll(".match-flag-checkbox");
                        matchCheckboxes.forEach((cb) => {
                            if (cb.checked) matchCount += 1;
                        });
                    }

                    // ★ゲーム種別に応じて per_court を切り替え
                    const gameTypeInput = document.getElementById("id_game_type");
                    const gameType = gameTypeInput ? gameTypeInput.value : "doubles";
                    const perCourt = gameType === "singles" ? 2 : 4;

                    // ★最大面数を計算（サーバ側ロジックと同じ）
                    let maxCourts = 1;
                    if (matchCount >= perCourt) {
                        maxCourts = Math.max(1, Math.floor(matchCount / perCourt));
                    }

                    // 0 人の場合は一応 1〜8 面を許可（お好みで調整可）
                    if (matchCount === 0) {
                        maxCourts = 8;
                    }

                    val += step;
                    if (val < 1) val = 1;
                    if (val > maxCourts) val = maxCourts;
                    input.value = val;
                    return;
                }

                if (targetId === "num_rounds") {
                    val += step;
                    if (val < 1) val = 1;
                    if (val > 20) val = 20;
                    input.value = val;
                }
            });
        });


        // フォーム submit → AJAX だけ動かす
        if (matchForm) {
            matchForm.addEventListener("submit", (e) => {
                e.preventDefault();
                ajaxGenerateSchedule();
                modal.classList.remove("is-open");
                modal.setAttribute("aria-hidden", "true");
            });
        }
    }
    
    // =============================
    // 4) スコア入力（「-」クリックで編集）
    // =============================
    const scheduleArea = document.getElementById("schedule-area");

    if (scheduleArea) {
        scheduleArea.addEventListener("click", (e) => {
            const scoreSpan = e.target.closest(".tb-score");
            if (!scoreSpan) return;

            // すでに編集中なら何もしない
            if (scoreSpan.dataset.editing === "1") return;
            scoreSpan.dataset.editing = "1";

            const currentText = scoreSpan.textContent.trim();
            const currentValue = currentText === "-" ? "" : currentText;

            // 入力欄を作成
            const input = document.createElement("input");
            input.type = "number";
            input.className = "tb-score-input";
            input.value = currentValue;

            // span の中身を入れ替え
            scoreSpan.textContent = "";
            scoreSpan.appendChild(input);
            input.focus();
            input.select();

            const finishEdit = (cancel = false) => {
                const val = cancel ? currentValue : input.value.trim();
                scoreSpan.removeAttribute("data-editing");

                if (val === "") {
                    scoreSpan.textContent = "-";
                } else {
                    scoreSpan.textContent = val;
                }
            };

            // フォーカスが外れたら確定
            input.addEventListener("blur", () => {
                finishEdit(false);
            });

            // Enterで確定 / Escでキャンセル
            input.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter") {
                    ev.preventDefault();
                    input.blur();
                } else if (ev.key === "Escape") {
                    ev.preventDefault();
                    finishEdit(true);
                    // blur を二重で呼ばないように
                }
            });
        });
    }


});

// =============================
// 3) 対戦表公開ボタン（従来どおり）
// =============================
window.publishSchedule = function () {
    const btn = document.getElementById("publish-pill");
    if (!btn) return;

    const state = btn.dataset.publishState;
    if (state === "no_schedule" || state === "published") {
        return;
    }

    const scriptTag = document.getElementById("current-schedule-json");
    if (!scriptTag) {
        alert("対戦表がまだ生成されていません。");
        return;
    }

    const eventId = scriptTag.dataset.eventId;
    const publishUrl = scriptTag.dataset.publishUrl;
    const scheduleJson = scriptTag.textContent.trim();

    const formData = new FormData();
    formData.append("event_id", eventId);
    formData.append("schedule_json", scheduleJson);

    fetch(publishUrl, {
        method: "POST",
        body: formData,
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.error) {
                console.error("publish error:", data.error);
                alert("公開に失敗しました: " + data.error);
                return;
            }

            btn.dataset.publishState = "published";
            btn.textContent = "公開済み";
            btn.classList.add("pill-disabled");
            btn.disabled = true;

            const notice = document.getElementById("publish-notice");
            if (notice) {
                notice.remove();
            }

            alert("対戦表を公開しました。");
        })
        .catch((err) => {
            console.error("network error:", err);
            alert("公開に失敗しました（ネットワークエラー）");
        });
};
