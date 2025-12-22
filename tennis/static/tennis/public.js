// tennis/static/tennis/public.js
document.addEventListener("DOMContentLoaded", () => {
  const csrftoken = (function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  })("csrftoken");

  // スコア編集（spanクリック → 入力 → 保存）
  document.querySelectorAll(".tb-score[data-match-id][data-save-url]").forEach((el) => {
    el.style.cursor = "pointer";

    el.addEventListener("click", async () => {
      const matchId = el.dataset.matchId;
      const saveUrl = el.dataset.saveUrl;

      // 左右スコアはセットで保存する想定に寄せる（片側クリックでも両方聞く）
      const currentLeft = document.querySelector(`.tb-score-left[data-match-id="${matchId}"]`)?.textContent?.trim() || "-";
      const currentRight = document.querySelector(`.tb-score-right[data-match-id="${matchId}"]`)?.textContent?.trim() || "-";

      const left = window.prompt("左（team1）のスコアを入力", currentLeft === "-" ? "" : currentLeft);
      if (left === null) return;

      const right = window.prompt("右（team2）のスコアを入力", currentRight === "-" ? "" : currentRight);
      if (right === null) return;

      const leftNum = left === "" ? null : Number(left);
      const rightNum = right === "" ? null : Number(right);

      if ((leftNum !== null && !Number.isInteger(leftNum)) || (rightNum !== null && !Number.isInteger(rightNum))) {
        UI?.showMessage?.("スコアは整数で入力してください。", 2600);
        return;
      }

      const fd = new FormData();
      fd.append("match_id", matchId);
      fd.append("score1", leftNum === null ? "" : String(leftNum));
      fd.append("score2", rightNum === null ? "" : String(rightNum));

      try {
        const res = await fetch(saveUrl, {
          method: "POST",
          headers: csrftoken ? { "X-CSRFToken": csrftoken } : {},
          body: fd,
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          UI?.showMessage?.(data.message || "保存に失敗しました。", 2600);
          return;
        }

        // 表示更新（APIが返すキーが違っても最低限反映）
        const s1 = (data.score1 ?? leftNum ?? "-");
        const s2 = (data.score2 ?? rightNum ?? "-");

        const leftEl = document.querySelector(`.tb-score-left[data-match-id="${matchId}"]`);
        const rightEl = document.querySelector(`.tb-score-right[data-match-id="${matchId}"]`);
        if (leftEl) leftEl.textContent = (s1 === "" || s1 === null) ? "-" : String(s1);
        if (rightEl) rightEl.textContent = (s2 === "" || s2 === null) ? "-" : String(s2);

        UI?.showMessage?.("スコアを保存しました。", 1400);
      } catch (e) {
        UI?.showMessage?.("通信エラーで保存できませんでした。", 2600);
      }
    });
  });
});

