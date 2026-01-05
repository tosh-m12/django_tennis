// tennis/static/tennis/event.js
// event.html 統合用：public/admin 共通（コメント/フラグ/出欠/ゲスト追加）＋ admin機能（試合参加/生成/公開/スコア）
//
// 目的：機能を変えずに「読みやすさ・保守性」を上げる整理版
// - ユーティリティ / 参加者特定 / 各機能ブロックをセクション分割
// - ガードは早期 return で統一
// - “未定義呼び出し” を作らないため、各機能はブロック内に閉じる
//
// ★既存仕様は維持（挙動変更なし）
// - 公開後の一般ユーザー編集ロック
// - 幹事の公開後編集は初回のみ confirm
// - 終了イベントの出欠変更ガード
// - 初回生成ゲート（hasScheduleEverGenerated）
// - iOS スコア編集の 1タップテンキー対策
// - event meta 編集（club-event-modal 流用）
// - 代打（公開済みのみ）
//
// ------------------------------------------------------------

(function () {
  // ============================================================
  // [UTIL] basic helpers
  // ============================================================
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
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

  // UI.confirm があれば使う。無ければ window.confirm
  // - 返り値は常に Promise<boolean>
  function safeConfirm(message, opts = {}) {
    const ui = window.UI;

    try {
      if (ui?.confirm) {
        // ★二重呼び出し防止：Promiseラップで常に 1 回
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


  
  // ============================================================
  // [UTIL] participant id helpers (ep_id / member_id)
  // ============================================================
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

    // row 自体
    row.dataset.epId = v;
    row.setAttribute("data-ep-id", v);

    // row 内の data-ep-id 保持要素も更新（行内のどこをクリックしても取れるように）
    qsa("[data-ep-id]", row).forEach((n) => n.setAttribute("data-ep-id", v));
  }

  // 参加者指定：ep_id があれば ep_id、無ければ member_id
  // - ids は element 由来、row は fallback
  function appendParticipant(fd, ids, row) {
    let epId = (ids?.epId || "").trim();
    let memberId = (ids?.memberId || "").trim();

    if (!epId && row) epId = String(row.dataset.epId || "").trim();
    if (!memberId && row) memberId = String(row.dataset.memberId || "").trim();

    if (epId) fd.append("ep_id", epId);
    else if (memberId) fd.append("member_id", memberId);
  }

  // ============================================================
  // boot
  // ============================================================
  document.addEventListener("DOMContentLoaded", () => {
    const csrftoken = getCookie("csrftoken");
    const participantsTable = document.getElementById("participants-table");
    if (!participantsTable) return;

    // ------------------------------------------------------------
    // [CTX] page context
    // ------------------------------------------------------------
    const isAdmin = toBool01(participantsTable.dataset.isAdmin);
    const eventId = participantsTable.dataset.eventId;

    const publishStateInit = (participantsTable.dataset.publishState || "").trim();
    const isPublishedInit = publishStateInit === "published";

    // ★公開後編集の1回確認フラグ（未定義だと全クリックが死ぬ）
    let adminConfirmedAfterPublish = false;

    // ------------------------------------------------------------
    // [SCHEDULE] 初回生成ゲート
    // - 既に生成済み（current-schedule-json がある等）なら true
    // - 初回生成前は、参加者増減で自動生成しない
    // ------------------------------------------------------------
    let hasScheduleEverGenerated = false;
    const scriptTagInit = document.getElementById("current-schedule-json");
    if (scriptTagInit && (scriptTagInit.textContent || "").trim()) {
      hasScheduleEverGenerated = true;
    }

    // 公開後：一般は操作不可
    const lockPublicEdits = !isAdmin && isPublishedInit;

    function blockPublicEdit(msg) {
      safeShowMessage(msg || "対戦表確定後の出欠変更は幹事へ申請してください", 2200);
    }

    // 公開後：幹事は最初の1回だけ警告 confirm
    async function warnIfAdminEditingPublished() {
      // ※ publishState は UI 更新で変わるので最新を取る（後述 getPublishState() を使う）
      if (!isAdmin) return true;
      if (getPublishState() !== "published") return true;
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

      if (!endHHMM) return false;

      const endAt = parseLocalDateTime(dateYmd, endHHMM);
      if (!endAt) return false;

      return now.getTime() > endAt.getTime();
    }

    // 終了イベントの出席者変更ガード
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

    // ============================================================
    // URLs (data-* から取得)
    // ============================================================
    const urls = {
      updateAttendance: participantsTable.dataset.updateAttendanceUrl,
      updateComment: participantsTable.dataset.updateCommentUrl,
      toggleFlag: participantsTable.dataset.toggleFlagUrl,
      setFlagValue: participantsTable.dataset.setFlagValueUrl,
      setParticipatesMatch: participantsTable.dataset.setParticipatesMatchUrl,
      addGuest: participantsTable.dataset.addGuestUrl,
      publish: participantsTable.dataset.publishUrl,
      saveScore: participantsTable.dataset.saveScoreUrl,
      setMemberClass: participantsTable.dataset.setMemberClassUrl,
    };

    function getClubIdSafe() {
      const v1 = String(participantsTable?.dataset?.clubId || "").trim();
      if (v1) return v1;

      const hooks = document.getElementById("event-edit-hooks");
      const v2 = String(hooks?.dataset?.clubId || "").trim();
      if (v2) return v2;

      const metaBar = document.getElementById("event-meta-bar");
      const v3 = String(metaBar?.dataset?.clubId || "").trim();
      if (v3) return v3;

      return "";
    }

    function getAdminTokenSafe() {
      const v1 = String(participantsTable?.dataset?.adminToken || "").trim();
      if (v1) return v1;

      const hooks = document.getElementById("event-edit-hooks");
      const v2 = String(hooks?.dataset?.adminToken || "").trim();
      if (v2) return v2;

      const metaBar = document.getElementById("event-meta-bar");
      const v3 = String(metaBar?.dataset?.adminToken || "").trim();
      if (v3) return v3;

      return "";
    }


    function getPublishState() {
      const table = document.getElementById("participants-table");
      const st1 = (table?.dataset?.publishState || "").trim();
      if (st1) return st1;

      const pill = document.getElementById("publish-pill");
      const st2 = (pill?.dataset?.publishState || "").trim();
      if (st2) return st2;

      return "no_schedule";
    }

    function setPublishStateUI(state) {
      const btn = document.getElementById("publish-pill");
      if (!btn) return;

      btn.dataset.publishState = state;

      // disabled と文言を状態に合わせる（既存UI仕様に沿う）
      if (state === "no_schedule") {
        btn.disabled = true;
        btn.classList.add("pill-disabled");
        btn.textContent = "📢 対戦表を公開";
        return;
      }

      btn.disabled = false;
      btn.classList.remove("pill-disabled");

      if (state === "published") {
        btn.textContent = "公開済み";
      } else if (state === "changed") {
        btn.textContent = "再公開";
      } else {
        // ready
        btn.textContent = "📢 対戦表を公開";
      }
    }

    function markChangedIfPublishedExists() {
      const cur = getPublishState();
      if (cur === "published") {
        setPublishStateUI("changed");
      }
    }

    // ============================================================
    // [INIT] メンバークラス select 初期値同期（ID優先→名前fallback）
    //  - data-current-class-id があればそれを最優先（新規作成のデフォルトを壊さない）
    //  - なければ data-current-class-name を option.text で探す
    //  - どっちも当たらなければ “現状の selected を維持” して title だけ付ける
    // ============================================================
    document.querySelectorAll(".member-class-select").forEach((sel) => {
      const curId = (sel.dataset.currentClassId || "").trim();
      const curName = (sel.dataset.currentClassName || "").trim();

      const opts = Array.from(sel.options || []);

      // 1) ID優先（存在する値なら合わせる）
      if (curId) {
        const hitById = opts.find((o) => String(o.value) === curId);
        if (hitById) {
          if (sel.value !== curId) sel.value = curId;
          sel.removeAttribute("title");
          return;
        }
        // curId はあるが現行optionsに無い（クラス削除など）→ fallbackへ
      }

      // 2) 名前fallback（表示名で一致）
      if (curName) {
        const hitByName = opts.find((o) => (o.textContent || "").trim() === curName);
        if (hitByName) {
          if (sel.value !== hitByName.value) sel.value = hitByName.value;
          sel.removeAttribute("title");
          return;
        }

        // 3) どちらも当たらない → “空にしない”（サーバ選択を尊重）
        //    ただし参照用にtitleだけ付与
        sel.title = `過去クラス: ${curName}`;
      } else {
        sel.removeAttribute("title");
      }
    });

    // ============================================================
    // [ADMIN] メンバーのクラス変更（event画面：コメント左のselect）
    //  - イベント固有スナップショット：EventParticipant.class_name を更新
    //  - Member は更新しない（クラブ既定は別画面）
    //  - 未登録固定行（ep_id 空）でも event_id + member_id で EP を作って保存する
    //  - 変更した瞬間に即保存（保存ボタンなし）
    //  - 固定メンバー未登録行（ep_id 空）の場合でも、event_id を使ってEPを作って event_member_class を保存できる
    // ============================================================
    (function initMemberClassChange() {
      if (!isAdmin || !urls?.setMemberClass || !participantsTable) return;

      if (!csrftoken) {
        console.warn("[member-class] csrftoken missing");
        return;
      }

      const clubId = getClubIdSafe();
      const adminToken = getAdminTokenSafe();

      // ここが空なら100%失敗するので、原因を見える化
      if (!clubId) console.warn("[member-class] club_id missing (data-club-id)");
      if (!adminToken) console.warn("[member-class] admin_token missing (data-admin-token)");

      participantsTable.addEventListener("focusin", (e) => {
        const sel = e.target.closest(".member-class-select");
        if (!sel) return;
        sel.dataset.prevValue = sel.value;
      });

      participantsTable.addEventListener("change", async (e) => {
        const sel = e.target.closest(".member-class-select");
        if (!sel || sel.disabled) return;

        const row = sel.closest("tr.participant-row");

        // event_id は必須（未EP行でEP作成するため）
        const eventIdLocal = String(participantsTable.dataset.eventId || "").trim();
        if (!eventIdLocal) {
          console.warn("[member-class] eventId missing on participantsTable");
          return;
        }

        // class_id: "" = 解除
        const classId = String(sel.value || "").trim();
        const prev = sel.dataset.prevValue ?? "";

        // ep_id: あれば優先（ゲスト/固定未登録の両対応）
        const epId =
          String(sel.dataset.epId || "").trim() ||
          String(row?.dataset?.epId || "").trim();

        // member_id: 固定未登録行で必要（EPが無ければ member_id で作る）
        const memberId =
          String(sel.dataset.memberId || "").trim() ||
          String(row?.dataset?.memberId || "").trim();

        // ★重要：member_id が無くても ep_id があれば保存できる
        //         両方無いなら保存先が特定できないので終了
        if (!epId && !memberId) {
          console.warn("[member-class] both ep_id and member_id are missing");
          safeShowMessage("保存先が特定できないためクラス変更できません（ep_id/member_id不足）", 2600);
          return;
        }

        // club_id は安全確認用（viewsが受ける想定）
        const clubId = getClubIdSafe();
        if (!clubId) console.warn("[member-class] club_id missing (data-club-id)");

        sel.disabled = true;

        const fd = new FormData();
        fd.append("event_id", eventIdLocal);
        if (clubId) fd.append("club_id", clubId);

        // participant 指定（ep優先、無ければ member）
        if (epId) fd.append("ep_id", epId);
        if (!epId && memberId) fd.append("member_id", memberId);

        fd.append("class_id", classId);

        // admin_token は views 側が見ても見なくてもOK（送って害なし）
        const adminToken = getAdminTokenSafe();
        if (adminToken) fd.append("admin_token", adminToken);

        try {
          const r = await fetch(urls.setMemberClass, {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });

          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) throw new Error(data?.error || "not ok");

          // 成功：prev 更新
          sel.dataset.prevValue = sel.value;

          // ★未登録行なら ep_id が返る → 行全体に反映（これが最重要）
          if (data.ep_id && row) {
            const newEpId = String(data.ep_id);
            applyEpIdToRow(row, newEpId);
            sel.dataset.epId = newEpId;
          }

          // ★表示の正は FK（id+name）なので両方更新しておく
          // views が class_id を返しているならそれを採用
          if (data.class_id !== undefined && data.class_id !== null) {
            sel.dataset.currentClassId = String(data.class_id);
          } else {
            // 解除時など
            sel.dataset.currentClassId = "";
          }

          sel.dataset.currentClassName = String(data.class_name || "").trim();

          // title は「削除済みクラス」等のフォールバック確認用
          if (sel.dataset.currentClassName) {
            sel.title = `class: ${sel.dataset.currentClassName}`;
          } else {
            sel.removeAttribute("title");
          }
        } catch (err) {
          console.error(err);
          safeShowMessage("クラス更新に失敗しました", 2600);
          sel.value = prev; // rollback

          // title 整合（あれば）
          const n = (sel.dataset.currentClassName || "").trim();
          if (n) sel.title = `class: ${n}`;
          else sel.removeAttribute("title");
        } finally {
          sel.disabled = false;
        }
      });

    })();


    // ============================================================
    // [UI] 出欠で行を並び替え（✓ → ? → ×）
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

      // 安定ソート用：初期indexを保存
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

    sortParticipantsByAttendance(); // 初期表示でも一度並び替え

    // ============================================================
    // [COMMON] コメント保存（blur + debounce）
    // ============================================================
    (function initComments() {
      if (!urls.updateComment) return;

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
    })();

    // ============================================================
    // [COMMON] フラグON/OFF（保存）
    //  - display-settings-modal を誤爆しない
    //  - 参加者テーブル内だけ
    // ============================================================
    (function initFlagsToggle() {
      if (!urls.toggleFlag) return;

      participantsTable.addEventListener("click", async (e) => {
        const btn = e.target.closest(".toggle-check");
        if (!btn) return;

        // ✅ display-settings-modal 内は event.js の担当外
        if (btn.closest("#display-settings-modal")) return;

        // ✅ 参加者テーブル外は誤爆防止（基本は不要だが安全策）
        if (!btn.closest("#participants-table")) return;

        // digit入力列は click で toggle しない
        if (btn.closest("td")?.querySelector('[data-input-mode="digit"]')) return;

        const flagId = (btn.dataset.flagId || "").trim();
        if (!flagId) return;

        // match toggle は別ロジック
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

        const adminToken = participantsTable.dataset.adminToken;
        if (adminToken) fd.append("admin_token", adminToken);

        try {
          const r = await fetch(urls.toggleFlag, {
            method: "POST",
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) throw new Error("not ok");
          if (data.ep_id) applyEpIdToRow(row, data.ep_id);
        } catch {
          // rollback
          btn.classList.toggle("is-on", !willOn);
          if (icon) {
            icon.classList.toggle("check-on", !willOn);
            icon.classList.toggle("check-off", willOn);
          }
          safeShowMessage("フラグ更新に失敗しました", 2600);
        }
      });
    })();

    // ============================================================
    // [COMMON] 数値フラグ（digit）保存（1桁）
    // ============================================================
    (function initDigitFlags() {
      if (!urls.setFlagValue) return;

      qsa('.flag-digit-input[data-input-mode="digit"]', participantsTable).forEach((input) => {
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

          const adminToken = participantsTable.dataset.adminToken;
          if (adminToken) fd.append("admin_token", adminToken);

          try {
            const r = await fetch(urls.setFlagValue, {
              method: "POST",
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
    })();

    // ============================================================
    // [COMMON] 出欠モーダル + 保存（admin/public 共通）
    //  - attendance=yes のときだけ 試合参加列を表示
    // ============================================================
    function setMatchVisible(row, visible) {
      if (!row) return;
      const btn = row.querySelector(".match-toggle");
      if (!btn) return;
      btn.classList.toggle("is-hidden", !visible);
    }

    // attendance=yes のときは試合参加 = ON に寄せる（既存仕様）
    // - ここは「UI変更 + サーバ保存」をセットで行う
    async function setParticipatesMatchForRow(row, checked) {
      if (!row || !urls.setParticipatesMatch) return false;

      const btn = row.querySelector('.toggle-check[data-kind="match"]');
      if (!btn) return false;

      const isOn = btn.classList.contains("is-on");
      if ((checked && isOn) || (!checked && !isOn)) return true;

      btn.classList.toggle("is-on", checked);
      const icon = btn.querySelector(".check-icon");
      if (icon) {
        icon.classList.toggle("check-on", checked);
        icon.classList.toggle("check-off", !checked);
      }

      const ids = getIdsFromEl(btn);
      const fd = new FormData();
      fd.append("event_id", eventId);
      appendParticipant(fd, ids, row);
      fd.append("checked", checked ? "1" : "0");

      try {
        const r = await fetch(urls.setParticipatesMatch, {
          method: "POST",
          headers: { "X-CSRFToken": csrftoken },
          body: fd,
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) throw new Error("not ok");
        if (data.ep_id) applyEpIdToRow(row, data.ep_id);
        return true;
      } catch {
        // rollback
        btn.classList.toggle("is-on", !checked);
        if (icon) {
          icon.classList.toggle("check-on", !checked);
          icon.classList.toggle("check-off", checked);
        }
        return false;
      }
    }

    (function initAttendanceModal() {
      if (!urls.updateAttendance) return;

      const modal = document.getElementById("attendance-modal");
      const closeBtn = document.getElementById("close-attendance-modal");
      if (!modal) return;

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
            currentBtn.dataset.attendance = attendance;

            if (isAdmin) {
              const willShowMatch = attendance === "yes";
              setMatchVisible(row, willShowMatch);

              // 出席=○ のときは試合参加もON（失敗時はメッセージ）
              const ok = await setParticipatesMatchForRow(row, willShowMatch);
              if (!ok) {
                safeShowMessage("試合参加の更新に失敗しました（再試行してください）", 2600);
              }

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
    })();

    // ============================================================
    // [COMMON] 参加登録（ゲスト追加）
    // ============================================================
    (function initAddGuest() {
      if (!urls.addGuest) return;

      const addBtn = document.getElementById("add-guest-btn");

      const modal = document.getElementById("add-guest-modal");
      const closeBtn = document.getElementById("close-add-guest-modal");
      const form = document.getElementById("add-guest-form");
      const input = document.getElementById("guest-name-input");

      if (!(addBtn && modal && form && input)) return;

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
        if (lockPublicEdits) return blockPublicEdit("対戦表公開後の出欠変更は幹事へ申請してください");
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
    })();

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
      // <4 → 0 / 4-7 → 1 / 8+ → 2（デフォルトは最大2）
      if (matchCount < 4) return 0;
      if (matchCount < 8) return 1;
      return 2;
    }

    function getCourtsMaxByCurrentState() {
      const gt = document.getElementById("id_game_type")?.value || "doubles";
      const matchCount = getMatchCountFromCheckboxes();
      const perCourt = gt === "singles" ? 2 : 4;

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

      // ★「手動で面数を変えていない」or「直近も自動値だった」なら自動追従
      const shouldAutoFollow =
        (!courtsManuallySet) || (lastAutoCourts !== null && v === lastAutoCourts);

      if (shouldAutoFollow) v = autoClamped;

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

      // ゲーム種別ピル同期（生成はしない）
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

      // モーダル内人数も同期
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

        // publish 用 JSON をDOMに保存
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

        // ★成功したら「生成済み」にする
        hasScheduleEverGenerated = true;

        // 初回生成直後：公開ボタンを有効化
        const cur = getPublishState();
        if (cur === "published") setPublishStateUI("changed");
        else setPublishStateUI("ready");

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

        markChangedIfPublishedExists();
        syncCourtsLimitByCurrentState();
      } catch (err) {
        console.error(err);
        safeShowMessage("対戦表の再生成に失敗しました（ネットワーク）", 2600);
      }
    }

    // ============================================================
    // [COMMON] 試合参加 ON/OFF（admin/public 共通）
    // ============================================================
    (function initMatchToggle() {
      if (!urls.setParticipatesMatch) return;

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
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });
          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) throw new Error("not ok");
          if (data.ep_id) applyEpIdToRow(row, data.ep_id);

          if (isAdmin) {
            markChangedIfPublishedExists();
            updateSettingsPillsLive();
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
    })();

    // ============================================================
    // [ADMIN] 条件モーダル（生成トリガ）
    // ============================================================
    (function initMatchSettingsModal() {
      if (!isAdmin) return;

      const modal = document.getElementById("match-settings-modal");
      const matchForm = document.getElementById("match-settings-form");
      if (!(modal && matchForm)) return;

      const triggers = qsa(".settings-trigger");
      const closeBtn = document.getElementById("close-settings-modal");

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

      // ★手動で面数を触ったら以降は自動追従を止める（ただし直近が自動値のままなら追従可）
      const numCourtsInput = document.getElementById("id_num_courts");
      if (numCourtsInput) {
        numCourtsInput.addEventListener("change", () => {
          courtsManuallySet = true;
        });
        numCourtsInput.addEventListener("input", () => {
          courtsManuallySet = true;
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
            // ★他の計算と統一：0面も許容する
            const maxCourts = getCourtsMaxByCurrentState(); // 0..8

            val += step;

            // clamp: 0..max
            if (val < 0) val = 0;
            if (val > maxCourts) val = maxCourts;

            input.value = String(val);

            // ここを触った＝手動扱い
            courtsManuallySet = true;
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
    })();

    // ============================================================
    // [COMMON] スコア inline edit（iOS対策あり）
    // ============================================================
    (function initInlineScoreEdit() {
      if (!urls.saveScore) return;

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
        input.type = isIOS ? "tel" : "number"; // iOSテンキーは tel が安定
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

            // 互換：バックエンドがどのキーを見ても良いよう複数で送る（既存踏襲）
            fd.append("value", nextVal);
            fd.append("score", nextVal);
            fd.append("score_value", nextVal);
            fd.append("team_no", side === "a" ? "1" : "2");

            const r = await fetch(saveUrl, {
              method: "POST",
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

      // iOS は click より touchend が安定（1タップでテンキー）
      document.addEventListener("pointerup", handler, true);
      document.addEventListener("touchend", handler, { capture: true, passive: false });
    })();

    // ============================================================
    // [ADMIN] 公開（global） ※既存通り window.publishSchedule を提供
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
              cancelText: "中止",
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
    // 重要ポイント：
    // - 「メタ変更」と「表示設定変更」を区別する（表示設定だけの変更でも"保存"扱いができる）
    // - dirty 判定が到達不能にならないように構成する
    // ============================================================
    (function initEventMetaEdit() {
      if (!isAdmin) return;

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

      if (!(metaBar && modal && form && updateUrl && adminToken)) return;

      let watchersAttached = false;
      let initialSnapshot = null;
      let isDirty = false;

      // 表示設定だけの変更を拾うためのフラグ
      // - ui_modal.js 側が displaySettingsChanged を dispatch すると想定
      let displaySettingsDirty = false;

      // club_id は participantsTable から取れる（無いなら ""）
      const clubIdForStorage = (participantsTable?.dataset?.clubId || "").trim();

      // 表示設定モーダルが保存したことを拾う
      document.addEventListener("displaySettingsChanged", () => {
        displaySettingsDirty = true;

        // 編集モード中なら更新ボタンを有効化
        if ((mode?.value || "").trim() === "edit") {
          setSubmitState(true, true);
        }
      });

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

      // ★重要：meta変更と表示設定変更を分ける
      // - metaDirty: 入力値（タイトル/場所/時間）の変更
      // - displaySettingsDirty: 表示設定モーダル保存だけの変更
      function computeMetaDirty() {
        if (!initialSnapshot) return false;
        const cur = snapshotNow();
        return (
          cur.title !== initialSnapshot.title ||
          cur.place !== initialSnapshot.place ||
          cur.start !== initialSnapshot.start ||
          cur.end !== initialSnapshot.end
        );
      }

      function computeDirty() {
        // 「更新ボタンの enable/disable」向け：どちらかが変われば dirty
        return computeMetaDirty() || !!displaySettingsDirty;
      }

      function setSubmitState(editMode, dirty) {
        if (!submitBtn) return;
        if (!editMode) return;

        submitBtn.textContent = "保存";

        const disabled = !dirty;
        submitBtn.disabled = disabled;
        submitBtn.classList.toggle("pill-disabled", disabled);
        submitBtn.classList.toggle("is-disabled", disabled);
      }

      function updateDirtyState() {
        if ((mode?.value || "").trim() !== "edit") return;

        syncHiddenTime();

        const d = computeDirty();
        if (d === isDirty) return;

        isDirty = d;
        setSubmitState(true, isDirty);
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
      // open: metaBar click → edit mode
      // ============================================================
      metaBar.addEventListener("click", () => {
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

        // 表示設定変更フラグは、編集開始時点では false に戻す
        // （表示設定だけ変えたケースの判定を正しくする）
        displaySettingsDirty = false;

        setSubmitState(true, false);

        openModal();
      });

      // ============================================================
      // cancel toggle: close → confirm → update
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

          // いったん閉じて確認（モーダルの二重状態を避ける）
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
      // submit (edit only)
      // ============================================================
      form.addEventListener("submit", async (ev) => {
        const currentMode = (mode?.value || "create").trim();
        if (currentMode !== "edit") return;

        ev.preventDefault();

        syncHiddenTime();

        const metaDirty = computeMetaDirty();
        const anyDirty = metaDirty || displaySettingsDirty;

        // 変更なし
        if (!anyDirty) {
          safeShowMessage("変更がありません", 1600);
          return;
        }

        // ★表示設定だけが変わった場合：
        // - サーバ更新は不要（表示設定は別API/別保存で完結している想定）
        // - ただし「保存したよ」扱いにして閉じる＆通知する
        if (!metaDirty && displaySettingsDirty) {
          displaySettingsDirty = false;

          isDirty = false;
          setSubmitState(true, false);

          closeModal();
          safeShowMessage("表示設定を保存しました", 1600);

          try {
            localStorage.setItem(
              "tennis_event_updated",
              JSON.stringify({
                club_id: clubIdForStorage,
                event_id: String(eventId),
                updated_at: Date.now(),
              })
            );
          } catch {}

          return;
        }

        // ★meta が変わっている → サーバ更新
        const prevDisabled = submitBtn?.disabled;
        if (submitBtn) submitBtn.disabled = true;

        const fd = new FormData(form);
        fd.set("event_id", String(eventId));
        fd.set("admin_token", adminToken);

        try {
          const r = await fetch(updateUrl, {
            method: "POST",
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

          // dataset 同期（次回編集の初期表示に効く）
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
          document.title = (data.event.title || "") + " - 幹事用";

          // snapshot 更新（dirty リセット）
          initialSnapshot = {
            title: (data.event.title || "").trim(),
            place: (data.event.place || "").trim(),
            start: (data.event.start_time || "").trim(),
            end: (data.event.end_time || "").trim(),
          };
          isDirty = false;
          displaySettingsDirty = false;

          setSubmitState(true, false);

          closeModal();
          safeShowMessage("更新しました", 1600);

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
    })();

    // ============================================================
    // [COMMON] 代打（公開済みのみ）
    // ============================================================
    (function initSubstitute() {
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
        if (subSelect.options.length > 1) return; // 二重投入しない

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

        // 公開済みでのみ代打可能（一般もOK）
        const canEditScore = (scheduleArea.dataset.canEditScore || "0") === "1";
        if (!canEditScore) {
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
        if (!subTarget) return;

        const newEpId = (subSelect?.value || "").trim();
        if (!newEpId) {
          safeShowMessage("代打を選択してください", 2000);
          return;
        }

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
            headers: { "X-CSRFToken": csrftoken },
            body: fd,
          });

          const data = await r.json().catch(() => ({}));
          if (!r.ok || !data.ok) {
            console.error("substitute failed:", r.status, data);
            safeShowMessage("代打の反映に失敗しました", 2600);
            return;
          }

          const scheduleArea = document.getElementById("schedule-area");
          if (scheduleArea && typeof data.schedule_html === "string") {
            scheduleArea.innerHTML = data.schedule_html;
          }

          if (isAdmin) markChangedIfPublishedExists();

          safeShowMessage("代打を反映しました。（スコアは再入力してください）", 2200);
          closeSub();
        } catch (e) {
          console.error(e);
          safeShowMessage("代打の反映に失敗しました（ネットワーク）", 2600);
        }
      });
    })();

    // init: admin only
    if (isAdmin) syncCourtsLimitByCurrentState();
  });
})();
