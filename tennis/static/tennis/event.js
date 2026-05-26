// tennis/static/tennis/event.js
// event.html 統合用：public/admin 共通（コメント/フラグ/出欠/ゲスト追加）＋ admin機能（試合参加/生成/公開/スコア）
// ★修正点：イベント編集モーダルの「中止/復活」押下でモーダルが閉じない問題を解消
//          - 中止/復活 click を submit の外で 1 回だけ登録
//          - 成功時に close() する
//          - close() で mode を create に戻す（状態残り防止）
//          - click に preventDefault/stopPropagation を付与

(function () {

  let csrftoken = "";

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  function getCsrfTokenFromMeta() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return (meta?.getAttribute("content") || "").trim();
  }

  function qsa(sel, root = document) {
    return Array.from(root.querySelectorAll(sel));
  }
  function toBool01(v) {
    return String(v || "") === "1";
  }
  function safeShowMessage(msg, ms = 2200) {
    if (window.UI?.showMessage) window.UI.showMessage(msg, ms);
    else alert(msg);
  }

  function safeConfirm(message, opts = {}) {
    const ui = window.UI;

    try {
      if (ui?.confirm) {
        // ★二重呼び出し防止：常に Promise ラップで 1 回だけ呼ぶ
        return new Promise((resolve) => {
          ui.confirm(message, {
            title: opts.title || "確認",
            okText: opts.okText || "OK",
            cancelText: opts.cancelText || "キャンセル",
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
            onClose: () => resolve(false),
          });
        });
      }
    } catch (e) {
      console.warn("UI.confirm failed, fallback to window.confirm", e);
    }

    return Promise.resolve(window.confirm(message));
  }


  function getRowFromEl(el) {
    return el?.closest?.("tr.participant-row") || null;
  }
  function getIdsFromEl(el) {
    const epId = (el?.getAttribute?.("data-ep-id") || el?.dataset?.epId || "").trim();
    const memberId = (el?.getAttribute?.("data-member-id") || el?.dataset?.memberId || "").trim();
    return { epId, memberId };
  }

  function applyEpIdToRow(row, newEpId) {
    if (!row || !newEpId) return;
    const v = String(newEpId);

    // row の data-ep-id を更新
    row.dataset.epId = v;      // data-ep-id に反映されるのは row が data-ep-id を持つ場合
    row.setAttribute("data-ep-id", v); // ★確実に属性を更新

    // row内の全ての data-ep-id 保持要素も更新（ボタン/コメントdiv等）
    qsa("[data-ep-id]", row).forEach((n) => n.setAttribute("data-ep-id", v));

    // ついでに ep_id を読む側が data-ep-id なら、これで次回確実に拾える
  }


  // 参加者指定：epがあれば ep_id、なければ member_id
  function appendParticipant(fd, ids, row) {
    // 1) element側
    let epId = (ids?.epId || "").trim();
    let memberId = (ids?.memberId || "").trim();

    // 2) row側にフォールバック（←ここが肝）
    if (!epId && row) epId = String(row.dataset.epId || "").trim();
    if (!memberId && row) memberId = String(row.dataset.memberId || "").trim();

    if (epId) fd.append("ep_id", epId);
    else if (memberId) fd.append("member_id", memberId);
  }


  document.addEventListener("DOMContentLoaded", () => {
    csrftoken = getCsrfTokenFromMeta();
    // フォールバック（念のため残すなら）
    if (!csrftoken) csrftoken = getCookie("csrftoken") || "";
    const participantsTable = document.getElementById("participants-table");
    if (!participantsTable) return;

    const isAdmin = toBool01(participantsTable.dataset.isAdmin);
    const eventId = participantsTable.dataset.eventId;

    const publishState = (participantsTable.dataset.publishState || "").trim();
    const isPublished = publishState === "published";

    // ★追加：公開後編集の1回確認フラグ（未定義だと全クリックが死ぬ）
    let adminConfirmedAfterPublish = false;


    // ------------------------------------------------------------
    // 初回生成ゲート
    // - 既に生成済み（current-schedule-json がある等）なら true
    // - 初回生成前は、参加者増減で自動生成しない
    // ------------------------------------------------------------
    let hasScheduleEverGenerated = false;

    const scriptTagInit = document.getElementById("current-schedule-json");
    if (scriptTagInit && (scriptTagInit.textContent || "").trim()) {
      hasScheduleEverGenerated = true;
    }

    // 公開後：一般は操作不可
    const lockPublicEdits = !isAdmin && isPublished;

    // 公開後：幹事も警告を出す（最初の1回だけ確認）
    async function warnIfAdminEditingPublished() {
      if (!isAdmin || !isPublished) return true;
      if (adminConfirmedAfterPublish) return true;

      const msg =
        "この対戦表は公開済みです。\n" +
        "出欠/試合参加を変更すると対戦表とズレが生じるため\n" +
        "「再公開」が必要です。続行しますか？";

      const ok = await safeConfirm(msg, {
        title: "確認",
        okText: "続行",
        cancelText: "中止",
      });

      if (ok) adminConfirmedAfterPublish = true;
      return ok;
    }

    function blockPublicEdit(msg) {
      safeShowMessage(msg || "対戦表確定後の出欠変更は幹事へ申請してください", 2200);
    }

    // ============================================================
    // [GUARD] 終了イベント判定（出席者変更だけ制御）
    // ============================================================
    const metaBarForGuard = document.getElementById("event-meta-bar");

    function parseLocalDateTime(dateYmd, hhmm) {
      if (!dateYmd) return null;
      const t = hhmm && hhmm.includes(":") ? hhmm : "00:00";
      const d = new Date(`${dateYmd}T${t}:00`);
      return isNaN(d.getTime()) ? null : d;
    }

    // 終了判定：
    // - 過去日 → 終了
    // - 今日 かつ end_time がある → now > end_time で終了
    // - end_time 無し → 今日分は「終了扱いにしない」
    function isEventEndedNow() {
      if (!metaBarForGuard) return false;

      const dateYmd = (metaBarForGuard.dataset.date || "").trim(); // "YYYY-MM-DD"
      const endHHMM = (metaBarForGuard.dataset.end || "").trim(); // "HH:MM" or ""

      if (!dateYmd) return false;

      const now = new Date();
      const todayYmd = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(
        2,
        "0"
      )}-${String(now.getDate()).padStart(2, "0")}`;

      if (dateYmd < todayYmd) return true;
      if (dateYmd > todayYmd) return false;

      // 今日：end が無いなら終了扱いにしない
      if (!endHHMM) return false;

      const endAt = parseLocalDateTime(dateYmd, endHHMM);
      if (!endAt) return false;

      return now.getTime() > endAt.getTime();
    }

    // 終了イベントの出席者変更ガード：
    // - 一般：ブロック + 警告
    // - 幹事：confirm（1回OKしたら以降は聞かない）
    let adminConfirmedForEndedEvent = false;

    async function guardParticipantChangeIfEnded() {
      const ended = isEventEndedNow();
      if (!ended) return true;

      if (!isAdmin) {
        safeShowMessage(
          "終了したイベントに対する出席者変更は幹事へ申請してください",
          2600
        );
        return false;
      }

      if (adminConfirmedForEndedEvent) return true;

      const ok = await safeConfirm("終了したイベントです。\n出席者変更しますか？", {
        title: "確認",
        okText: "変更",
        cancelText: "中止",
      });

      if (ok) adminConfirmedForEndedEvent = true;
      return ok;
    }

    const urls = {
      updateAttendance: participantsTable.dataset.updateAttendanceUrl,
      updateComment: participantsTable.dataset.updateCommentUrl,
      updateName: participantsTable.dataset.updateNameUrl,
      toggleFlag: participantsTable.dataset.toggleFlagUrl,
      setFlagValue: participantsTable.dataset.setFlagValueUrl,
      setParticipatesMatch: participantsTable.dataset.setParticipatesMatchUrl,
      addGuest: participantsTable.dataset.addGuestUrl,
      publish: participantsTable.dataset.publishUrl,
      saveScore: participantsTable.dataset.saveScoreUrl,
      setMemberClass: participantsTable.dataset.setMemberClassUrl,
    };


    // ============================================================
    // [HELPERS] publish pill state
    // ============================================================
    function getPublishBtn() {
      return document.getElementById("publish-pill");
    }

    function getPublishState() {
      // 0) participants-table（admin/public 共通で存在）
      const s0 = (participantsTable?.dataset?.publishState || participantsTable?.dataset?.publish_state || "").trim();
      if (s0) return s0;

      // 1) admin UI の publish pill（adminだけ）
      const btn = getPublishBtn();
      const s1 = (btn?.dataset?.publishState || btn?.dataset?.publish_state || "").trim();
      if (s1) return s1;

      return "";
    }

    function setPublishStateUI(state) {
      if (participantsTable) participantsTable.dataset.publishState = state;

      const btn = getPublishBtn();
      if (!btn) return;

      // ★ 初回生成前は必ず no_schedule に固定
      if (!hasScheduleEverGenerated) {
        btn.dataset.publishState = "no_schedule";
        btn.textContent = "📢 対戦表を公開";
        btn.disabled = true;
        btn.classList.add("pill-disabled");
        return;
      }

      btn.dataset.publishState = state;

      btn.classList.remove("pill-disabled");
      btn.disabled = false;

      if (state === "no_schedule") {
        btn.textContent = "📢 対戦表を公開";
        btn.disabled = true;
        btn.classList.add("pill-disabled");
        return;
      }

      if (state === "ready") {
        btn.textContent = "📢 対戦表を公開";
        btn.disabled = false;
        btn.classList.remove("pill-disabled");
        return;
      }


      if (state === "published") {
        btn.textContent = "公開済み";
        btn.disabled = true;
        btn.classList.add("pill-disabled");
        return;
      }
      if (state === "changed") {
        btn.textContent = "再公開";
        return;
      }

      btn.textContent = "📢 対戦表を公開";
    }


    function markChangedIfPublishedExists() {
      // ★ そもそも未生成なら publishState を触らない
      if (!hasScheduleEverGenerated) {
        setPublishStateUI("no_schedule");
        return;
      }

      const state = getPublishState();
      if (state === "published") {
        setPublishStateUI("changed");
        if (!window.hasShownChangedNotice) {
          safeShowMessage(
            "対戦表が更新されました。\n参加者ページへ反映するには「再公開」を押してください。",
            3000
          );
          window.hasShownChangedNotice = true;
        }
      }
    }


    function setMatchVisible(row, visible) {
      if (!row) return;
      const btn = row.querySelector(".match-toggle");
      if (!btn) return;
      btn.classList.toggle("is-hidden", !visible);
    }

    // 試合参加チェックの「見た目」だけ更新する（POSTはしない）。
    // 出欠変更時は update_attendance が試合参加も確定・返却するため、
    // ここでは応答値に合わせて表示を同期するだけにする（二重POST防止）。
    function setMatchToggleUI(row, on) {
      if (!row) return;
      const btn = row.querySelector('.toggle-check[data-kind="match"]');
      if (!btn) return;
      const isOn = !!on;
      btn.classList.toggle("is-on", isOn);
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", isOn);
        icon.classList.toggle("check-off", !isOn);
      }
    }

    // ============================================================
    // [UI] 出欠で行を並び替え（✓ → ? → ×）
    //  - yes: ✓
    //  - maybe/""(未回答): ?
    //  - no: ×
    //  - 同一グループ内は元の順番を維持（安定）
    //  - 左端の連番も振り直す
    // ============================================================
    function sortParticipantsByAttendance() {
      const tbody = participantsTable.querySelector("tbody");
      if (!tbody) return;

      const rows = Array.from(tbody.querySelectorAll("tr.participant-row"));
      if (!rows.length) return;

      const order = { yes: 0, maybe: 1, no: 2, "": 3 };

      function getAttendance(tr) {
        const btn = tr.querySelector(".attendance-btn");
        const v = (btn?.dataset?.attendance || "").trim();
        if (v === "yes" || v === "maybe" || v === "no") return v;
        return ""; // 未回答は "?" 扱い
      }

      // 安定ソート用：初期indexを保存（同グループ内の順序を崩さない）
      rows.forEach((tr, i) => {
        if (!tr.dataset.origIndex) tr.dataset.origIndex = String(i);
      });

      rows.sort((a, b) => {
        const ao = order[getAttendance(a)] ?? 1;
        const bo = order[getAttendance(b)] ?? 1;
        if (ao !== bo) return ao - bo;

        const ai = parseInt(a.dataset.origIndex || "0", 10);
        const bi = parseInt(b.dataset.origIndex || "0", 10);
        return ai - bi;
      });

      const frag = document.createDocumentFragment();
      rows.forEach((tr, i) => {
        const idxEl = tr.querySelector(".participant-index .idx");
        if (idxEl) idxEl.textContent = String(i + 1);
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    // ★初期表示でも一度並び替え
    sortParticipantsByAttendance();


    // ============================================================
    // [COMMON] コメント保存（blur + debounce）
    // ============================================================
    if (urls.updateComment) {
      qsa(".comment-editable", participantsTable).forEach((div) => {
        let timer = null;
        let lastSent = null;

        const post = async () => {
          const row = getRowFromEl(div);
          const ids = getIdsFromEl(div);
          const comment = (div.textContent || "").trim();
          const key = `${ids.epId || ids.memberId}:${comment}`;
          if (key === lastSent) return;

          const fd = new FormData();
          fd.append("event_id", eventId);
          appendParticipant(fd, ids, row);
          fd.append("comment", comment);

          lastSent = key;

          try {
            const r = await fetch(urls.updateComment, {
              method: "POST",
              credentials: "include",
              headers: { "X-CSRFToken": csrftoken },
              body: fd,
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
              lastSent = null;
              return;
            }
            if (data.ep_id) applyEpIdToRow(row, data.ep_id);
          } catch {
            lastSent = null;
          }
        };

        div.addEventListener("blur", post);
        div.addEventListener("input", () => {
          if (timer) clearTimeout(timer);
          timer = setTimeout(post, 600);
        });
      });
    }

    // ============================================================
    // [COMMON] フラグON/OFF（保存）
    // ============================================================
    if (urls.toggleFlag) {
      participantsTable.addEventListener("click", async (e) => {
        const btn = e.target.closest(".toggle-check");
        if (!btn) return;

        if (btn.closest("td")?.querySelector('[data-input-mode="digit"]')) {
          return;
        }

        const flagId = (btn.dataset.flagId || "").trim();
        if (!flagId) return;

        if ((btn.dataset.kind || "") === "match") return;

        const row = getRowFromEl(btn);
        const ids = getIdsFromEl(btn);

        const willOn = !btn.classList.contains("is-on");
        btn.classList.toggle("is-on", willOn);

        const icon = btn.querySelector(".check-icon");
        if (icon) {
          icon.classList.toggle("check-on", willOn);
          icon.classList.toggle("check-off", !willOn);
        }

        const fd = new FormData();
        fd.append("event_id", eventId);
        appendParticipant(fd, ids, row);
        fd.append("flag_id", flagId);
        fd.append("checked", willOn ? "1" : "0");
        fd.append("flag_scope", (btn.dataset.flagScope || "club"));

        try {
          const r = await fetch(urls.toggleFlag, {
            method: "POST",
            credentials: "include",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) throw new Error("not ok");
          if (data.ep_id) applyEpIdToRow(row, data.ep_id);
        } catch {
          btn.classList.toggle("is-on", !willOn);
          if (icon) {
            icon.classList.toggle("check-on", !willOn);
            icon.classList.toggle("check-off", willOn);
          }
          safeShowMessage("フラグ更新に失敗しました", 2600);
        }
      });
    }

    if (urls.setFlagValue) {
      qsa('.flag-digit-input[data-input-mode="digit"]', participantsTable)
        .forEach((input) => {
        let lastSent = null;

        const normalize = (v) => {
          const s = String(v || "").trim();
          if (s === "") return "";
          if (!/^\d$/.test(s)) return "";
          return s;
        };

        const post = async () => {
          const row = getRowFromEl(input);
          const ids = getIdsFromEl(input);
          const flagId = (input.dataset.flagId || "").trim();
          if (!flagId) return;

          const v = normalize(input.value);
          input.value = v;

          const key = `${ids.epId || ids.memberId}:${flagId}:${v}`;
          if (key === lastSent) return;
          lastSent = key;

          const fd = new FormData();
          fd.append("event_id", eventId);
          appendParticipant(fd, ids, row);
          fd.append("flag_id", flagId);
          fd.append("value", v); // "" = クリア
          fd.append("flag_scope", (input.dataset.flagScope || "club"));

          try {
            const r = await fetch(urls.setFlagValue, {
              method: "POST",
              credentials: "include",
              headers: { "X-CSRFToken": csrftoken },
              body: fd,
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) throw new Error("not ok");
            if (data.ep_id) applyEpIdToRow(row, data.ep_id);
          } catch (e) {
            console.error(e);
            lastSent = null;
            safeShowMessage("フラグ更新に失敗しました", 2600);
          }
        };

        input.addEventListener("input", () => {
          input.value = normalize(input.value).slice(0, 1);
        });
        input.addEventListener("blur", post);
        input.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            input.blur();
          } else if (ev.key === "Escape") {
            ev.preventDefault();
            input.value = "";
            input.blur();
          }
        });
      });
    }

    // ============================================================
    // [ADMIN] イベント側 チーム分け（クラス）保存
    // ============================================================
    if (isAdmin && urls.setMemberClass) {
      // 初期値保持（失敗時に戻す）
      qsa("select.participant-class-select", participantsTable).forEach((sel) => {
        sel.dataset.prev = (sel.value || "").trim();
      });

      participantsTable.addEventListener("change", async (e) => {
        const sel = e.target.closest("select.participant-class-select");
        if (!sel) return;

        if (lockPublicEdits) {
          // 公開後の一般編集は禁止（幹事だけ想定なので保険）
          sel.value = sel.dataset.prev || "";
          return blockPublicEdit("公開後の編集は幹事へ申請してください");
        }

        if (!(await warnIfAdminEditingPublished())) {
          sel.value = sel.dataset.prev || "";
          return;
        }

        if (!(await guardParticipantChangeIfEnded())) {
          sel.value = sel.dataset.prev || "";
          return;
        }

        const row = getRowFromEl(sel);
        const ids = getIdsFromEl(sel);

        const classId = (sel.value || "").trim(); // "" も許可（未所属）
        const prev = (sel.dataset.prev || "").trim();

        const fd = new FormData();
        fd.append("event_id", eventId);
        appendParticipant(fd, ids, row);
        fd.append("class_id", classId);

        const adminToken = participantsTable.dataset.adminToken;
        if (adminToken) fd.append("admin_token", adminToken);

        try {
          const r = await fetch(urls.setMemberClass, {
            method: "POST",
            credentials: "include",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) throw new Error(data.error || "not ok");

          if (data.ep_id) applyEpIdToRow(row, data.ep_id);

          sel.dataset.prev = classId;
          // safeShowMessage("クラスを保存しました", 1400);

          // 公開済みなら再公開導線
          markChangedIfPublishedExists();
        } catch (err) {
          console.error(err);
          sel.value = prev;
          safeShowMessage("クラス保存に失敗しました", 2200);
        }
      });
    }


    // ============================================================
    // [COMMON] 出欠モーダル + 保存（admin/public 共通）
    //  - attendance=yes のときだけ 試合参加列を表示
    // ============================================================
    if (urls.updateAttendance) {
      const modal = document.getElementById("attendance-modal");
      const closeBtn = document.getElementById("close-attendance-modal");
      if (modal) {
        let currentBtn = null;

        const open = () => {
          modal.classList.add("is-open");
          modal.setAttribute("aria-hidden", "false");
        };
        const close = () => {
          // aria-hidden 警告対策：中にフォーカスが残ってたら外す
          const active = document.activeElement;
          if (active && modal.contains(active)) active.blur();

          modal.classList.remove("is-open");
          modal.setAttribute("aria-hidden", "true");

          // ❌ hideEditOnlyButtons() は出欠モーダルでは不要（未定義で落ちる）
        };

        closeBtn?.addEventListener("click", close);
        modal.addEventListener("click", (ev) => {
          if (ev.target === modal) close();
        });
        document.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape" && modal.classList.contains("is-open")) close();
        });

        participantsTable.addEventListener("click", async (ev) => {
          const btn = ev.target.closest(".attendance-btn");
          if (!btn) return;

          if (lockPublicEdits) {
            ev.preventDefault();
            ev.stopPropagation();
            return blockPublicEdit("対戦表確定後の出欠変更は幹事へ申請してください");
          }

          // ★ここから await
          if (!(await warnIfAdminEditingPublished())) {
            ev.preventDefault();
            ev.stopPropagation();
            return;
          }

          if (!(await guardParticipantChangeIfEnded())) {
            ev.preventDefault();
            ev.stopPropagation();
            return;
          }

          currentBtn = btn;
          open();
        });

        qsa(".attendance-choice", modal).forEach((choice) => {
          choice.addEventListener("click", async () => {
            if (!currentBtn) return;

            const row = getRowFromEl(currentBtn);
            const ids = getIdsFromEl(currentBtn);
            const attendance = (choice.dataset.attendance || "").trim();

            const fd = new FormData();
            fd.append("event_id", eventId);
            appendParticipant(fd, ids, row);
            fd.append("attendance", attendance);

            try {
              const r = await fetch(urls.updateAttendance, {
                method: "POST",
                credentials: "include",
                headers: { "X-CSRFToken": csrftoken },
                body: fd,
              });
              const data = await r.json().catch(() => ({}));
              if (!r.ok || !data.ok) throw new Error("not ok");

              if (data.ep_id) applyEpIdToRow(row, data.ep_id);

              let html = `<span class="attendance-icon attendance-none">&nbsp;</span>`;
              if (attendance === "yes")
                html = `<span class="attendance-icon attendance-yes">✓</span>`;
              else if (attendance === "no")
                html = `<span class="attendance-icon attendance-no">×</span>`;
              else if (attendance === "maybe")
                html = `<span class="attendance-icon attendance-maybe">?</span>`;

              currentBtn.innerHTML = html;
              currentBtn.dataset.attendance = attendance; // "" のままでもOK

              if (isAdmin) {
                const willShowMatch = attendance === "yes";
                setMatchVisible(row, willShowMatch);

                // update_attendance が試合参加も確定・返却済み。
                // 2回目のPOSTはせず、応答値で見た目だけ同期する。
                // （出席のまま再選択しても、手動で外した不参加が維持される）
                setMatchToggleUI(row, !!data.participates_match);

                markChangedIfPublishedExists();
                updateSettingsPillsLive();
              }

              close();
            } catch {
              safeShowMessage("出欠の保存に失敗しました", 2600);
              close();
            }
          });
        });
      }
    }

    // ============================================================
    // [COMMON] 参加登録（モーダルで名前入力 → 保存）
    // ============================================================
    if (urls.addGuest) {
      const addBtn = document.getElementById("add-guest-btn");

      const modal = document.getElementById("add-guest-modal");
      const closeBtn = document.getElementById("close-add-guest-modal");
      const form = document.getElementById("add-guest-form");
      const input = document.getElementById("guest-name-input");

      if (addBtn && modal && form && input) {
        const open = () => {
          modal.classList.add("is-open");
          modal.setAttribute("aria-hidden", "false");
          input.value = "";
          setTimeout(() => input.focus(), 0);
        };

        const close = () => {
          modal.classList.remove("is-open");
          modal.setAttribute("aria-hidden", "true");
        };

        addBtn.addEventListener("click", async () => {
          if (lockPublicEdits)
            return blockPublicEdit("対戦表公開後の出欠変更は幹事へ申請してください");

          if (!(await warnIfAdminEditingPublished())) return;
          if (!(await guardParticipantChangeIfEnded())) return;

          open();
        });

        closeBtn?.addEventListener("click", close);

        modal.addEventListener("click", (ev) => {
          if (ev.target === modal) close();
        });

        document.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape" && modal.classList.contains("is-open")) close();
        });

        form.addEventListener("submit", async (ev) => {
          ev.preventDefault();

          const name = (input.value || "").trim();
          if (!name) {
            safeShowMessage("名前を入力してください", 2200);
            input.focus();
            return;
          }

          const fd = new FormData();
          fd.append("event_id", eventId);
          fd.append("display_name", name);

          const submitBtn = form.querySelector('button[type="submit"]');
          if (submitBtn) submitBtn.disabled = true;

          try {
            const r = await fetch(urls.addGuest, {
              method: "POST",
              credentials: "include",
              headers: { "X-CSRFToken": csrftoken },
              body: fd,
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) throw new Error("not ok");

            close();
            window.location.reload();
          } catch (err) {
            console.error(err);
            safeShowMessage("参加登録に失敗しました", 2600);
          } finally {
            if (submitBtn) submitBtn.disabled = false;
          }
        });
      }
    }

    // ============================================================
    // [NAME EDIT] 参加者名タップで編集（一般/幹事どちらも・公開後/終了後も可）
    // ============================================================
    if (urls.updateName) {
      const modal = document.getElementById("event-name-edit-modal");
      const closeBtn = document.getElementById("close-event-name-edit-modal");
      const form = document.getElementById("event-name-edit-form");
      const input = document.getElementById("event-name-edit-input");
      const hiddenEpId = document.getElementById("event-name-edit-ep-id");
      const hiddenMemberId = document.getElementById("event-name-edit-member-id");

      if (modal && form && input) {
        let targetNameEl = null;
        let targetRow = null;

        const open = (nameEl, row, epId, memberId, currentName) => {
          targetNameEl = nameEl;
          targetRow = row;
          hiddenEpId.value = epId || "";
          hiddenMemberId.value = memberId || "";
          input.value = currentName || "";
          modal.classList.add("is-open");
          modal.setAttribute("aria-hidden", "false");
          setTimeout(() => { input.focus(); input.select(); }, 0);
        };

        const close = () => {
          const active = document.activeElement;
          if (active && modal.contains(active)) active.blur();
          modal.classList.remove("is-open");
          modal.setAttribute("aria-hidden", "true");
          targetNameEl = null;
          targetRow = null;
        };

        // 名前セルのクリック/タップ → モーダルを開く（イベント委譲）
        participantsTable.addEventListener("click", (e) => {
          const nameEl = e.target.closest(".editable-name");
          if (!nameEl) return;
          const row = getRowFromEl(nameEl);
          if (!row) return;
          const epId = String(row.dataset.epId || "").trim();
          const memberId = String(row.dataset.memberId || "").trim();
          if (!epId && !memberId) return;
          open(nameEl, row, epId, memberId, (nameEl.textContent || "").trim());
        });

        closeBtn?.addEventListener("click", close);
        modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
        document.addEventListener("keydown", (e) => {
          if (e.key === "Escape" && modal.classList.contains("is-open")) close();
        });

        form.addEventListener("submit", async (e) => {
          e.preventDefault();

          const name = (input.value || "").trim();
          if (!name) {
            safeShowMessage("名前を入力してください", 2200);
            input.focus();
            return;
          }

          const fd = new FormData();
          fd.append("event_id", eventId);
          const epId = (hiddenEpId.value || "").trim();
          const memberId = (hiddenMemberId.value || "").trim();
          if (epId) fd.append("ep_id", epId);
          else if (memberId) fd.append("member_id", memberId);
          fd.append("display_name", name);

          const submitBtn = form.querySelector('button[type="submit"]');
          if (submitBtn) submitBtn.disabled = true;

          try {
            const r = await fetch(urls.updateName, {
              method: "POST",
              credentials: "include",
              headers: { "X-CSRFToken": csrftoken },
              body: fd,
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) throw new Error("not ok");

            if (targetNameEl) targetNameEl.textContent = data.display_name || name;
            if (targetRow && data.ep_id) applyEpIdToRow(targetRow, data.ep_id);
            close();
            safeShowMessage("名前を更新しました", 1600);
          } catch (err) {
            console.error(err);
            safeShowMessage("名前の更新に失敗しました", 2600);
          } finally {
            if (submitBtn) submitBtn.disabled = false;
          }
        });
      }
    }

    // ============================================================
    // [ADMIN] 試合参加 / 生成 / 公開 / スコア
    // ============================================================
    function getMatchCountFromCheckboxes() {
      let c = 0;
      qsa('.toggle-check[data-kind="match"]', participantsTable).forEach((b) => {
        if (b.classList.contains("is-on")) c += 1;
      });
      return c;
    }

    // ============================================================
    // [ADMIN] pills live update (NO schedule generation)
    // ============================================================
    let courtsManuallySet = false;
    let lastAutoCourts = null;

    function computeDefaultCourtsByCount(matchCount) {
      // ★要求仕様：<4 → 0 / 4-7 → 1 / 8+ → 2（どれだけ多くてもデフォルトは2）
      if (matchCount < 4) return 0;
      if (matchCount < 8) return 1;
      return 2;
    }

    function getCourtsMaxByCurrentState() {
      const gt = document.getElementById("id_game_type")?.value || "doubles";
      const matchCount = getMatchCountFromCheckboxes();
      const perCourt = gt === "singles" ? 2 : 4;

      // 0人～(perCourt-1)人 → 0面
      let maxCourts = Math.floor(matchCount / perCourt);
      if (maxCourts < 0) maxCourts = 0;
      if (maxCourts > 8) maxCourts = 8;
      return maxCourts;
    }

    function syncCourtsLimitByCurrentState() {
      const input = document.getElementById("id_num_courts");
      if (!input) return;

      const matchCount = getMatchCountFromCheckboxes();
      const maxCourts = getCourtsMaxByCurrentState();

      input.min = "0";
      input.max = String(maxCourts);

      const auto = computeDefaultCourtsByCount(matchCount);
      const autoClamped = Math.min(auto, maxCourts);

      let v = parseInt(input.value || "", 10);
      if (Number.isNaN(v)) v = autoClamped;

      // ★「手動で面数を変えていない」or「直近も自動値だった」場合は自動追従
      const shouldAutoFollow = (!courtsManuallySet);
      if (shouldAutoFollow) {
        v = autoClamped;
      }

      // clamp
      if (v < 0) v = 0;
      if (v > maxCourts) v = maxCourts;

      input.value = String(v);
      lastAutoCourts = autoClamped;
    }

    function updateSettingsPillsLive() {
      const pillMatchCount = document.getElementById("pill-match-count");
      const pillNumCourts = document.getElementById("pill-num-courts");
      const pillNumRounds = document.getElementById("pill-num-rounds");
      const pillGameType = document.getElementById("pill-game-type");

      const matchCount = getMatchCountFromCheckboxes();

      // ★面数の自動追従（ここで input.value が更新される）
      syncCourtsLimitByCurrentState();

      const courtsVal = parseInt(document.getElementById("id_num_courts")?.value || "0", 10) || 0;
      const roundsVal = parseInt(document.getElementById("id_num_rounds")?.value || "10", 10) || 10;
      const gt = document.getElementById("id_game_type")?.value || "doubles";

      if (pillMatchCount) pillMatchCount.textContent = `${matchCount} 人`;
      if (pillNumCourts) pillNumCourts.textContent = `${courtsVal} 面`;
      if (pillNumRounds) pillNumRounds.textContent = `${roundsVal} ラウンド`;

      // ついでにゲーム種別もピルは同期（生成はしない）
      if (pillGameType) {
        pillGameType.classList.remove("pill-singles", "pill-doubles");
        if (gt === "singles") {
          pillGameType.classList.add("pill-singles");
          pillGameType.textContent = "シングルス";
        } else {
          pillGameType.classList.add("pill-doubles");
          pillGameType.textContent = "ダブルス";
        }
      }

      // モーダル内の人数表示も同期（生成はしない）
      const modalCountPill = document.querySelector("#match-settings-modal .count-pill");
      if (modalCountPill) modalCountPill.textContent = String(matchCount);
    }

    function collectMatchParticipantEpIds() {
      const ids = [];
      qsa('.toggle-check[data-kind="match"]', participantsTable).forEach((b) => {
        if (!b.classList.contains("is-on")) return;

        let epId = (b.dataset.epId || "").trim();
        if (!epId) {
          const row = getRowFromEl(b);
          epId = (row?.dataset?.epId || "").trim();
        }
        if (epId) ids.push(epId);
      });
      return ids;
    }

    async function ajaxGenerateSchedule(force = false) {
      // ★初回生成前は「手動（force=true）」以外は生成しない
      if (!force && !hasScheduleEverGenerated) return;

      const matchForm = document.getElementById("match-settings-form");
      if (!matchForm) return;
      const url = matchForm.dataset.generateUrl;
      if (!url) return;

      const fd = new FormData();
      fd.append("participant_ids", collectMatchParticipantEpIds().join(","));
      fd.append("game_type", document.getElementById("id_game_type")?.value || "doubles");
      fd.append("num_courts", document.getElementById("id_num_courts")?.value || "1");
      fd.append("num_rounds", document.getElementById("id_num_rounds")?.value || "10");

      try {
        const r = await fetch(url, {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });

        const data = await r.json().catch(() => ({}));
        if (!r.ok || data.error) {
          safeShowMessage("対戦表の再生成に失敗しました", 2600);
          console.error(data);
          return;
        }

        const scheduleArea2 = document.getElementById("schedule-area");
        const statsArea2 = document.getElementById("stats-area");
        if (scheduleArea2 && typeof data.schedule_html === "string") scheduleArea2.innerHTML = data.schedule_html;
        if (statsArea2 && typeof data.stats_html === "string") statsArea2.innerHTML = data.stats_html;

        // ✅ 再生成直後は「未公開」扱いに落とす（残留値対策の保険）
        if (scheduleArea2) scheduleArea2.dataset.canEditScore = "0";

        // ===== ★追加：publish 用 JSON をDOMに保存 =====
        if (typeof data.schedule_json === "string" && data.schedule_json.trim()) {
          let st = document.getElementById("current-schedule-json");
          if (!st) {
            st = document.createElement("script");
            st.id = "current-schedule-json";
            st.type = "application/json";
            document.body.appendChild(st);
          }
          st.textContent = data.schedule_json;
        }

        // ★成功したら「生成済み」にする（ここが肝）
        hasScheduleEverGenerated = true;

        // ✅ 重要：再生成成功＝未公開の新スケジュール（draft）なので publishState は必ず ready
        //   - ここで published/chagned にすると「公開済み扱いで代打できてしまう」事故の土台になる
        setPublishStateUI("ready");

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
        if (pillNumCourts && data.num_courts !== undefined) pillNumCourts.textContent = `${data.num_courts} 面`;
        if (pillMatchCount && data.match_count !== undefined) pillMatchCount.textContent = `${data.match_count} 人`;
        if (pillNumRounds && data.num_rounds !== undefined) pillNumRounds.textContent = `${data.num_rounds} ラウンド`;

        const modalCountPill = document.querySelector("#match-settings-modal .count-pill");
        if (modalCountPill && data.match_count !== undefined) modalCountPill.textContent = String(data.match_count);

        // ✅ 再生成後は draft なので「published を前提にした changed 表示」は不要
        // markChangedIfPublishedExists();

        syncCourtsLimitByCurrentState();
      } catch (err) {
        console.error(err);
        safeShowMessage("対戦表の再生成に失敗しました（ネットワーク）", 2600);
      }
    }



    // ============================================================
    // [COMMON] 試合参加 ON/OFF（admin/public 共通）
    // ============================================================
    if (urls.setParticipatesMatch) {
      participantsTable.addEventListener("click", async (e) => {
        const btn = e.target.closest('.toggle-check[data-kind="match"]');
        if (!btn) return;

        if (lockPublicEdits) {
          e.preventDefault();
          e.stopPropagation();
          return blockPublicEdit("対戦表確定後の出欠変更は幹事へ申請してください");
        }

        if (!(await warnIfAdminEditingPublished())) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }

        if (!(await guardParticipantChangeIfEnded())) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }

        const row = getRowFromEl(btn);
        const ids = getIdsFromEl(btn);

        const willOn = !btn.classList.contains("is-on");
        btn.classList.toggle("is-on", willOn);

        const icon = btn.querySelector(".check-icon");
        if (icon) {
          icon.classList.toggle("check-on", willOn);
          icon.classList.toggle("check-off", !willOn);
        }

        const fd = new FormData();
        fd.append("event_id", eventId);
        appendParticipant(fd, ids, row);
        fd.append("checked", willOn ? "1" : "0");

        try {
          const r = await fetch(urls.setParticipatesMatch, {
            method: "POST",
            credentials: "include",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) throw new Error("not ok");
          if (data.ep_id) applyEpIdToRow(row, data.ep_id);

          if (isAdmin) {
            markChangedIfPublishedExists();
            updateSettingsPillsLive();   // ★ピルだけ更新
          }
        } catch {
          btn.classList.toggle("is-on", !willOn);
          if (icon) {
            icon.classList.toggle("check-on", !willOn);
            icon.classList.toggle("check-off", willOn);
          }
          safeShowMessage("試合参加の更新に失敗しました", 2600);
        }
      });
    }

    // admin: 条件モーダル
    if (isAdmin) {
      const modal = document.getElementById("match-settings-modal");
      const matchForm = document.getElementById("match-settings-form");
      if (modal && matchForm) {
        const triggers = qsa(".settings-trigger");
        const closeBtn = document.getElementById("close-settings-modal");

        // ★面数をユーザーが触ったら「手動」にする
        const courtsInput = document.getElementById("id_num_courts");
        if (courtsInput) {
          const markManual = () => { courtsManuallySet = true; };
          courtsInput.addEventListener("input", markManual);
          courtsInput.addEventListener("change", markManual);
        }

        const openModal = () => {
          const countPill = modal.querySelector(".count-pill");
          if (countPill) countPill.textContent = String(getMatchCountFromCheckboxes());
          syncCourtsLimitByCurrentState();
          modal.classList.add("is-open");
          modal.setAttribute("aria-hidden", "false");
        };
        const closeModal = () => {
          modal.classList.remove("is-open");
          modal.setAttribute("aria-hidden", "true");
        };

        triggers.forEach((b) => b.addEventListener("click", openModal));
        closeBtn?.addEventListener("click", closeModal);
        modal.addEventListener("click", (ev) => {
          if (ev.target === modal) closeModal();
        });
        document.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape" && modal.classList.contains("is-open")) closeModal();
        });

        const toggleBtns = qsa(".toggle-btn", modal);
        const gameTypeInput = document.getElementById("id_game_type");
        if (toggleBtns.length && gameTypeInput) {
          toggleBtns.forEach((btn) => {
            btn.addEventListener("click", () => {
              toggleBtns.forEach((b) => b.classList.remove("active"));
              btn.classList.add("active");
              const gt = btn.dataset.gameType;
              if (gt) gameTypeInput.value = gt;
              syncCourtsLimitByCurrentState();
            });
          });
        }

        qsa(".stepper-btn", modal).forEach((btn) => {
          btn.addEventListener("click", () => {
            const targetId = btn.dataset.target;
            const step = parseInt(btn.dataset.step, 10) || 1;
            const input = document.getElementById("id_" + targetId);
            if (!input) return;

            let val = parseInt(input.value || "0", 10);

            if (targetId === "num_courts") {
              courtsManuallySet = true;
              const matchCount = getMatchCountFromCheckboxes();
              const gt = document.getElementById("id_game_type")?.value || "doubles";
              const perCourt = gt === "singles" ? 2 : 4;

              let maxCourts = 1;
              if (matchCount >= perCourt) maxCourts = Math.max(1, Math.floor(matchCount / perCourt));
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

        matchForm.addEventListener("submit", (ev) => {
          ev.preventDefault();
          ajaxGenerateSchedule(true); // ★初回生成はここだけ
          closeModal();
        });
      }
    }

    // ============================================================
    // [COMMON] スコア inline edit（round_no/court_no/side）
    //  - iOS 対策：click ではなく pointerup/touchend を優先して
    //    “1タップでテンキー” を出す
    // ============================================================
    if (urls.saveScore) {
      const isIOS = /iP(hone|od|ad)/.test(navigator.userAgent);

      const handler = (e) => {
        const scheduleArea = document.getElementById("schedule-area");
        if (!scheduleArea || !scheduleArea.contains(e.target)) return;

        const canEditScore = (scheduleArea.dataset.canEditScore || "0") === "1";
        const scoreSpan = e.target.closest(".tb-score");
        if (!scoreSpan) return;

        if (!canEditScore) {
          e.preventDefault();
          e.stopPropagation();
          safeShowMessage("未公開の対戦表ではスコアを入力できません", 2200);
          return;
        }

        // 既に input 上なら何もしない
        if (e.target.closest(".tb-score-input")) return;

        // 2重起動防止
        if (scoreSpan.dataset.editing === "1") return;
        scoreSpan.dataset.editing = "1";

        // ★ここ重要：iOS で “ユーザー操作” として扱わせるため、
        // なるべくこのハンドラの同期処理内で input を作って focus する
        // （ただし scroll を邪魔しない範囲で）
        e.preventDefault();
        e.stopPropagation();

        const currentText = (scoreSpan.textContent || "").trim();
        const currentValue = currentText === "-" ? "" : currentText;

        const saveUrl = (urls.saveScore || "").trim();
        if (!saveUrl) {
          safeShowMessage("スコア保存URLが取得できません（data-save-score-url を確認）", 3000);
          scoreSpan.removeAttribute("data-editing");
          return;
        }

        const roundNo = (scoreSpan.dataset.roundNo || "").trim();
        const courtNo = (scoreSpan.dataset.courtNo || "").trim();
        const side = (scoreSpan.dataset.side || "").trim();

        if (!roundNo || !courtNo || !side) {
          safeShowMessage("スコア属性が不足しています（data-round-no / data-court-no / data-side）", 3000);
          scoreSpan.removeAttribute("data-editing");
          return;
        }

        const input = document.createElement("input");
        // ★iOSテンキー最優先：number より tel が安定
        input.type = isIOS ? "tel" : "number";
        input.inputMode = "numeric";
        input.pattern = "[0-9]*";
        input.autocomplete = "off";
        input.className = "tb-score-input";
        input.value = currentValue;

        // 親ハンドラに吸われないように
        input.addEventListener("pointerdown", (ev) => ev.stopPropagation());
        input.addEventListener("pointerup", (ev) => ev.stopPropagation());
        input.addEventListener("mousedown", (ev) => ev.stopPropagation());
        input.addEventListener("click", (ev) => ev.stopPropagation());
        input.addEventListener("touchstart", (ev) => ev.stopPropagation(), { passive: true });
        input.addEventListener("touchend", (ev) => ev.stopPropagation(), { passive: true });

        scoreSpan.textContent = "";
        scoreSpan.appendChild(input);

        // ★iOSは “今すぐ focus” が通りやすい
        // ただし通らない端末があるので 0ms で保険もかける
        try {
          input.focus({ preventScroll: true });
          input.select?.();
        } catch {}

        setTimeout(() => {
          try {
            input.focus({ preventScroll: true });
            input.select?.();
          } catch {}
        }, 0);

        const renderSpan = (v) => {
          const s = v === null || v === undefined ? "" : String(v).trim();
          scoreSpan.textContent = s === "" ? "-" : s;
        };

        const finishEdit = async (cancel = false) => {
          const nextVal = cancel ? currentValue : (input.value || "").trim();

          scoreSpan.removeAttribute("data-editing");
          renderSpan(nextVal);

          if (cancel) return;

          if (!csrftoken) {
            safeShowMessage("CSRFトークンが取得できません（csrftoken cookie を確認）", 3000);
            renderSpan(currentValue);
            return;
          }

          try {
            const fd = new FormData();
            fd.append("event_id", eventId);
            fd.append("round_no", roundNo);
            fd.append("court_no", courtNo);
            fd.append("side", side);

            fd.append("value", nextVal);
            fd.append("score", nextVal);
            fd.append("score_value", nextVal);
            fd.append("team_no", side === "a" ? "1" : "2");

            const r = await fetch(saveUrl, {
              method: "POST",
              credentials: "include",
              headers: { "X-CSRFToken": csrftoken },
              body: fd,
            });

            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
              console.error("save_score failed:", r.status, data);
              safeShowMessage("スコア保存に失敗しました", 2600);
              renderSpan(currentValue);
              return;
            }

            if (data.value !== undefined) renderSpan(data.value);
            if (data.score !== undefined) renderSpan(data.score);
          } catch (err) {
            console.error(err);
            safeShowMessage("スコア保存に失敗しました（ネットワーク）", 2600);
            renderSpan(currentValue);
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
      };

      // ★iOS は click より touchend が安定（1タップでテンキー）
      // ただし iPadOS なども含め pointerup を優先し、touchend を保険に。
      document.addEventListener("pointerup", handler, true);
      document.addEventListener("touchend", handler, { capture: true, passive: false });
    }


    // ============================================================
    // [ADMIN] 公開（global）
    // ============================================================
    window.publishSchedule = function () {
      const btn = document.getElementById("publish-pill");
      if (!btn) return;

      const state = btn.dataset.publishState;
      if (state === "no_schedule") {
        safeShowMessage("対戦表がまだ生成されていません。", 2600);
        return;
      }
      if (state === "published") return;

      const scriptTag = document.getElementById("current-schedule-json");
      if (!scriptTag) {
        safeShowMessage("対戦表がまだ生成されていません。", 2600);
        return;
      }

      const publishUrl = (urls.publish || "").trim() || (scriptTag.dataset.publishUrl || "").trim();
      const scheduleJson = (scriptTag.textContent || "").trim();

      if (!publishUrl || !scheduleJson) {
        safeShowMessage("公開に必要な情報が不足しています。", 2600);
        return;
      }

      const postPublish = async (force) => {
        const fd = new FormData();
        fd.append("event_id", eventId);
        fd.append("schedule_json", scheduleJson);
        if (force) fd.append("force", "1");

        const r = await fetch(publishUrl, {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });
        const data = await r.json().catch(() => ({}));
        return { r, data };
      };

      const applyPublishedUI = () => {
        setPublishStateUI("published");
        window.hasShownChangedNotice = false;
      };

      (async () => {
        try {
          let { r, data } = await postPublish(false);

          if (r.status === 409 && data && data.error === "score_exists") {
            const msg =
              data.message ||
              "スコアが登録されています。再公開すると登録済みスコアがリセットされますが、よろしいでしょうか？";

            const ok = await safeConfirm(msg, {
              title: "確認",
              okText: "スコアを破棄して再公開",
              cancelText: "やめる",
            });

            if (!ok) return;

            try {
              const res2 = await postPublish(true);
              if (!res2.r.ok || (res2.data && res2.data.error)) {
                safeShowMessage("公開に失敗しました。", 2600);
                console.error(res2.data);
                return;
              }

              applyPublishedUI();
              safeShowMessage("対戦表を公開しました。", 2200);
              setTimeout(() => window.location.reload(), 900);
            } catch (err2) {
              console.error(err2);
              safeShowMessage("公開に失敗しました（ネットワーク）。", 2600);
            }

            return;
          }


          if (!r.ok || (data && data.error)) {
            safeShowMessage("公開に失敗しました。", 2600);
            console.error(data);
            return;
          }

          applyPublishedUI();
          safeShowMessage("対戦表を公開しました。", 2200);
          setTimeout(() => window.location.reload(), 900);
        } catch (err) {
          console.error(err);
          safeShowMessage("公開に失敗しました（ネットワーク）。", 2600);
        }
      })();
    };

    // ============================================================
    // [ADMIN] イベントメタ編集：club-event-modal を流用（完成版 / 修正版）
    //  - metaBar クリックで編集モーダルを開く（←欠けていた）
    //  - dirty判定/hidden time 同期/submit制御をブロック内に内包（←未定義呼び出し根絶）
    //  - 中止/復活は「先に編集モーダルを閉じて」confirm → okなら更新 → reload
    // ============================================================
    if (isAdmin) {
      const metaBar = document.getElementById("event-meta-bar");
      const hooks = document.getElementById("event-edit-hooks");

      const updateUrl =
        (hooks?.dataset?.updateUrl || "").trim() ||
        (metaBar?.dataset?.updateUrl || "").trim();

      const adminToken =
        (hooks?.dataset?.adminToken || "").trim() ||
        (metaBar?.dataset?.adminToken || "").trim();

      const modal = document.getElementById("club-event-modal");
      const closeBtn = document.getElementById("club-event-modal-close");
      const form = document.getElementById("club-event-form");

      const cancelToggleBtn = document.getElementById("club-event-cancel-toggle");
      const submitBtn =
        document.getElementById("club-event-submit-btn") ||
        form?.querySelector?.('button[type="submit"]');

      const mode = document.getElementById("club-event-mode");
      const eventIdInput = document.getElementById("club-event-event-id");
      const titleEl = document.getElementById("club-event-modal-title");

      const dateText = document.getElementById("club-event-date-text");
      const dateHidden = document.getElementById("club-event-date");

      const inTitle = document.getElementById("club-event-title");
      const inPlace = document.getElementById("club-event-place");

      const sh = document.getElementById("club-start-hour");
      const sm = document.getElementById("club-start-min");
      const eh = document.getElementById("club-end-hour");
      const em = document.getElementById("club-end-min");

      const hiddenStart = document.getElementById("club-event-start-time");
      const hiddenEnd = document.getElementById("club-event-end-time");

      if (!metaBar) console.warn("[event-edit] metaBar missing");
      if (!modal) console.warn("[event-edit] club-event-modal missing (check _ui_modals include)");
      if (!form) console.warn("[event-edit] club-event-form missing");
      if (!updateUrl) console.warn("[event-edit] updateUrl missing (check event-edit-hooks / dataset)");
      if (!adminToken) console.warn("[event-edit] adminToken missing (check event-edit-hooks / dataset)");

      if (!(metaBar && modal && form && updateUrl && adminToken)) {
        // 必須不足なら何もしない（JS全体を落とさない）
      } else {
        let watchersAttached = false;
        let initialSnapshot = null;
        let isDirty = false;

        function showEditOnlyButtons() {
          if (cancelToggleBtn) cancelToggleBtn.style.display = "inline-flex";
        }
        function hideEditOnlyButtonsSafe() {
          if (cancelToggleBtn) cancelToggleBtn.style.display = "none";
        }

        function openModal() {
          modal.classList.add("is-open");
          modal.setAttribute("aria-hidden", "false");
        }

        function closeModal() {
          const active = document.activeElement;
          if (active && modal.contains(active)) active.blur();

          modal.classList.remove("is-open");
          modal.setAttribute("aria-hidden", "true");
          hideEditOnlyButtonsSafe();
        }

        closeBtn?.addEventListener("click", closeModal);
        modal.addEventListener("click", (ev) => {
          if (ev.target === modal) closeModal();
        });
        document.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape" && modal.classList.contains("is-open")) closeModal();
        });

        function setCancelToggleUI(cancelled) {
          if (!cancelToggleBtn) return;
          cancelToggleBtn.dataset.cancelled = cancelled ? "1" : "0";
          cancelToggleBtn.textContent = cancelled ? "中止を取り消す（復活）" : "イベントを中止";
        }

        function fillTimeSelects() {
          const hh = [...Array(24)].map((_, i) => String(i).padStart(2, "0"));
          const mm = ["00", "15", "30", "45"];
          [sh, eh].forEach((sel) => {
            if (sel) sel.innerHTML = hh.map((v) => `<option value="${v}">${v}</option>`).join("");
          });
          [sm, em].forEach((sel) => {
            if (sel) sel.innerHTML = mm.map((v) => `<option value="${v}">${v}</option>`).join("");
          });
        }

        function setTimeToSelects(startHHMM, endHHMM) {
          const [sH, sM] = (startHHMM || "").split(":");
          const [eH, eM] = (endHHMM || "").split(":");

          if (sH && sh) sh.value = sH;
          if (sM && sm) sm.value = sM;
          if (eH && eh) eh.value = eH;
          if (eM && em) em.value = eM;

          if (hiddenStart) hiddenStart.value = startHHMM || "";
          if (hiddenEnd) hiddenEnd.value = endHHMM || "";
        }

        function syncHiddenTime() {
          const s = sh?.value && sm?.value ? `${sh.value}:${sm.value}` : "";
          const e = eh?.value && em?.value ? `${eh.value}:${em.value}` : "";
          if (hiddenStart) hiddenStart.value = s;
          if (hiddenEnd) hiddenEnd.value = e;
        }

        function snapshotNow() {
          return {
            title: (inTitle?.value || "").trim(),
            place: (inPlace?.value || "").trim(),
            start: (hiddenStart?.value || "").trim(),
            end: (hiddenEnd?.value || "").trim(),
          };
        }

        function computeDirty() {
          if (!initialSnapshot) return false;
          const cur = snapshotNow();
          return (
            cur.title !== initialSnapshot.title ||
            cur.place !== initialSnapshot.place ||
            cur.start !== initialSnapshot.start ||
            cur.end !== initialSnapshot.end
          );
        }

        function setSubmitState(editMode, dirty) {
          if (!submitBtn) return;
          if (!editMode) return;

          submitBtn.textContent = "更新";

          submitBtn.disabled = false;
          submitBtn.classList.remove("pill-disabled", "is-disabled");
        }

        function updateDirtyState() {
          if ((mode?.value || "").trim() !== "edit") return;
          syncHiddenTime();

          const d = computeDirty();
          isDirty = d;

          setSubmitState(true, true);
        }

        function attachDirtyWatchersOnce() {
          if (watchersAttached) return;
          watchersAttached = true;

          [inTitle, inPlace].forEach((el) => {
            el?.addEventListener("input", updateDirtyState);
            el?.addEventListener("change", updateDirtyState);
          });
          [sh, sm, eh, em].forEach((sel) => {
            sel?.addEventListener("change", updateDirtyState);
          });
        }

        // ============================================================
        // ★開く：metaBar クリックで edit モード起動（←欠けていた）
        // ============================================================
        metaBar.addEventListener("click", () => {
          const until = window.__suppressMetaBarClickUntil || 0;
          if (until && Date.now() < until) {
            return;
          }
          if (mode) mode.value = "edit";
          if (titleEl) titleEl.textContent = "イベント編集";

          showEditOnlyButtons();

          const cancelled = (metaBar.dataset.cancelled || "").trim() === "1";
          setCancelToggleUI(cancelled);

          if (eventIdInput) eventIdInput.value = String(eventId);

          const d = (metaBar.dataset.date || "").trim();
          const t = (metaBar.dataset.title || "").trim();
          const p = (metaBar.dataset.place || "").trim();
          const s = (metaBar.dataset.start || "").trim();
          const e = (metaBar.dataset.end || "").trim();

          if (dateText) dateText.textContent = d || "—";
          if (dateHidden) dateHidden.value = d || "";

          if (inTitle) inTitle.value = t;
          if (inPlace) inPlace.value = p;

          fillTimeSelects();
          setTimeToSelects(s || "09:00", e || "12:00");

          attachDirtyWatchersOnce();
          syncHiddenTime();

          initialSnapshot = snapshotNow();
          isDirty = false;
          setSubmitState(true, true);

          openModal();
        });

        // ============================================================
        // 中止/復活：先に close → confirm → okなら更新
        // ============================================================
        modal.addEventListener(
          "click",
          async (ev) => {
            const btn = ev.target.closest("#club-event-cancel-toggle");
            if (!btn) return;

            ev.preventDefault();
            ev.stopPropagation();

            const nowCancelled = (btn.dataset.cancelled || "0") === "1";
            const nextCancelled = !nowCancelled;

            closeModal();

            const ok = await safeConfirm(
              nextCancelled ? "このイベントを中止しますか？" : "このイベントを復活させますか？",
              {
                title: "確認",
                okText: nextCancelled ? "中止する" : "復活する",
                cancelText: "やめる",
              }
            );

            if (!ok) {
              openModal();
              return;
            }

            const prevDisabled = btn.disabled;
            btn.disabled = true;

            const fd = new FormData();
            fd.set("event_id", String(eventId));
            fd.set("admin_token", adminToken);
            fd.set("cancelled", nextCancelled ? "1" : "0");

            try {
              const r = await fetch(updateUrl, {
                method: "POST",
                credentials: "include",
                headers: { "X-CSRFToken": csrftoken },
                body: fd,
              });
              const data = await r.json().catch(() => ({}));
              if (!r.ok || !data.ok) throw new Error("not ok");

              metaBar.dataset.cancelled = data.event.cancelled ? "1" : "0";
              setCancelToggleUI(!!data.event.cancelled);

              safeShowMessage(data.event.cancelled ? "中止にしました" : "復活しました", 1600);
              setTimeout(() => window.location.reload(), 1600);
            } catch (err) {
              console.error(err);
              safeShowMessage("中止状態の更新に失敗しました", 2600);
              openModal();
            } finally {
              btn.disabled = prevDisabled;
            }
          },
          true
        );

        // ============================================================
        // submit（編集のみ）: ★常に POST → close → reload
        // ============================================================
        form.addEventListener("submit", async (ev) => {
          const currentMode = (mode?.value || "create").trim();
          if (currentMode !== "edit") return;

          ev.preventDefault();

          // hidden time を確実に同期
          syncHiddenTime();

          const clubModalEl = form?.closest("#club-event-modal");

          // ボタン連打防止
          const prevDisabled = submitBtn?.disabled;
          if (submitBtn) submitBtn.disabled = true;

          // ★「表示されている内容をそのままDBへ」なので FormData(form) を素直に使う
          const fd = new FormData(form);
          fd.set("event_id", String(eventId));
          fd.set("admin_token", adminToken);

          try {
            const r = await fetch(updateUrl, {
              method: "POST",
              credentials: "include",
              headers: { "X-CSRFToken": csrftoken },
              body: fd,
            });

            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
              console.error(data);
              safeShowMessage("イベント更新に失敗しました", 2600);
              if (submitBtn) submitBtn.disabled = !!prevDisabled;
              return;
            }

            // ---- 既存のメタ更新などは維持（ただし最終的に reload するので必須ではないが残す） ----
            metaBar.dataset.date = data.event.date || "";
            metaBar.dataset.title = data.event.title || "";
            metaBar.dataset.place = data.event.place || "";
            metaBar.dataset.start = data.event.start_time || "";
            metaBar.dataset.end = data.event.end_time || "";
            if (data.event.cancelled !== undefined) {
              metaBar.dataset.cancelled = data.event.cancelled ? "1" : "0";
              setCancelToggleUI(!!data.event.cancelled);
            }

            const metaText2 = document.getElementById("event-meta-text");
            if (metaText2 && data.event.meta_text) metaText2.textContent = data.event.meta_text;

            const h2 = document.querySelector(".event-title");
            if (h2) h2.textContent = data.event.title || "";

            // title 反映（ただし reload する）
            if (data.event.title) {
              document.title = (data.event.title || "") + " - 幹事用";
            }

            // snapshot を更新（内部整合のため）
            initialSnapshot = {
              title: (data.event.title || "").trim(),
              place: (data.event.place || "").trim(),
              start: (data.event.start_time || "").trim(),
              end: (data.event.end_time || "").trim(),
            };
            isDirty = false;

            // ★表示設定 dirty もクリア（念のため）
            if (clubModalEl) clubModalEl.dataset.displaySettingsDirty = "0";

            closeModal();
            // safeShowMessage("更新しました", 800);

            // ★仕様：更新押下後は常にリロード
            setTimeout(() => window.location.reload(), 80);

            try {
              localStorage.setItem(
                "tennis_event_updated",
                JSON.stringify({
                  club_id: data.event.club_id,
                  event_id: data.event.id,
                  updated_at: Date.now(),
                })
              );
            } catch {}
          } catch (err) {
            console.error(err);
            safeShowMessage("イベント更新に失敗しました（ネットワーク）", 2600);
            if (submitBtn) submitBtn.disabled = !!prevDisabled;
          }
        });
      }
    }

    // ============================================================
    // [COMMON] 代打（名前カード click → modal → apply）【修正版】
    //  - ✅ 未公開(draft)では代打禁止（裏に公開済みがあっても禁止）
    //  - ✅ 判定は data-can-edit-score ではなく publishState を使用
    // ============================================================
    const subUrl = (participantsTable.dataset.substituteUrl || "").trim();
    const subModal = document.getElementById("substitute-modal");
    const subClose = document.getElementById("close-substitute-modal");
    const subOk = document.getElementById("substitute-ok-btn");
    const subSelect = document.getElementById("substitute-select");
    const candScript = document.getElementById("sub-candidates-json");

    let subTarget = null; // {roundNo,courtNo,team,slotIndex,oldEpId}

    function openSub() {
      if (!subModal) return;
      subModal.classList.add("is-open");
      subModal.setAttribute("aria-hidden", "false");
    }

    function closeSub() {
      if (!subModal) return;
      const active = document.activeElement;
      if (active && subModal.contains(active)) active.blur();

      subModal.classList.remove("is-open");
      subModal.setAttribute("aria-hidden", "true");

      subTarget = null;
      if (subSelect) subSelect.value = "";
    }

    // 候補を select に詰める（attendance=yes 想定）
    (function initSubCandidatesOnce() {
      if (!subSelect) return;

      // 既に option が入っているなら二重投入しない
      if (subSelect.options.length > 1) return;

      if (!candScript) {
        console.warn("[substitute] sub-candidates-json not found");
        return;
      }

      try {
        const cands = JSON.parse((candScript.textContent || "[]").trim() || "[]");
        cands.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = String(c.ep_id);
          opt.textContent = c.name || String(c.ep_id);
          subSelect.appendChild(opt);
        });
      } catch (e) {
        console.warn("failed to parse sub-candidates-json", e);
      }
    })();

    // モーダル閉じ
    subClose?.addEventListener("click", closeSub);
    subModal?.addEventListener("click", (ev) => {
      if (ev.target === subModal) closeSub();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && subModal?.classList.contains("is-open")) closeSub();
    });

    // 名前カード click → 代打モーダル
    document.addEventListener("click", (ev) => {
      const card = ev.target.closest(".js-sub-slot");
      if (!card) return;

      const scheduleArea = document.getElementById("schedule-area");
      if (!scheduleArea || !scheduleArea.contains(card)) return;

      const state = getPublishState(); // published / changed を許可
      const canSubstitute = (state === "published" || state === "changed");
      if (!canSubstitute) {
        safeShowMessage("未公開の対戦表では代打設定できません（公開後に可能）", 2200);
        return;
      }

      if (!subUrl) {
        safeShowMessage("代打URLが設定されていません（participants-table の data-substitute-url）", 3000);
        return;
      }

      // 候補ゼロガード（placeholder 1個だけの場合）
      if (!subSelect || subSelect.options.length <= 1) {
        safeShowMessage("代打候補がありません（出席=○ の人がいません）", 2200);
        return;
      }

      subTarget = {
        roundNo: (card.dataset.roundNo || "").trim(),
        courtNo: (card.dataset.courtNo || "").trim(),
        team: (card.dataset.team || "").trim(),
        slotIndex: (card.dataset.slotIndex || "").trim(),
        oldEpId: (card.dataset.epId || "").trim(),
      };

      openSub();
    });

    // 適用
    subOk?.addEventListener("click", async () => {
      const state = getPublishState();
      const canSubstitute = (state === "published" || state === "changed");
      if (!canSubstitute) {
        safeShowMessage("未公開の対戦表では代打設定できません（公開後に可能）", 2200);
        closeSub();
        return;
      }


      if (!subTarget) return;

      const newEpId = (subSelect?.value || "").trim();
      if (!newEpId) {
        safeShowMessage("代打を選択してください", 2000);
        return;
      }

      // 同一人物選択は何もしない
      if (subTarget.oldEpId && String(subTarget.oldEpId) === String(newEpId)) {
        safeShowMessage("同じ人が選択されています", 1800);
        return;
      }

      const fd = new FormData();
      fd.append("event_id", eventId);
      fd.append("round_no", subTarget.roundNo);
      fd.append("court_no", subTarget.courtNo);
      fd.append("team", subTarget.team);
      fd.append("slot_index", subTarget.slotIndex);
      fd.append("new_ep_id", newEpId);
      if (subTarget.oldEpId) fd.append("old_ep_id", subTarget.oldEpId);

      try {
        const r = await fetch(subUrl, {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });

        const data = await r.json().catch(() => ({}));

        if (!r.ok || !data.ok) {
          // ✅ サーバ側ガード対応（後述の draft_exists）
          if (data && data.error === "draft_exists") {
            safeShowMessage("未公開の対戦表では代打設定できません（公開後に可能）", 2200);
            closeSub();
            return;
          }

          console.error("substitute failed:", r.status, data);
          safeShowMessage("代打の反映に失敗しました", 2600);
          return;
        }

        // schedule 差し替え
        const scheduleArea = document.getElementById("schedule-area");
        if (scheduleArea && typeof data.schedule_html === "string") {
          scheduleArea.innerHTML = data.schedule_html;
        }

        // ✅ 仕様：代打は「公開済み対戦表の修正」なので公開状態は維持する
        //  - 再公開(changed)にはしない
        //  - UIが崩れて未公開表示になるのを防ぐため、明示的に published に固定
        if (participantsTable) participantsTable.dataset.publishState = "published";
        if (typeof setPublishStateUI === "function") setPublishStateUI("published");
        if (scheduleArea) scheduleArea.dataset.canEditScore = "1"; // 公開済み扱いを維持（必要なら）


        safeShowMessage("代打を反映しました。（スコアは再入力してください）", 2200);
        closeSub();
      } catch (e) {
        console.error(e);
        safeShowMessage("代打の反映に失敗しました（ネットワーク）", 2600);
      }
    });



    // init
    if (isAdmin) syncCourtsLimitByCurrentState();
  });
})();
