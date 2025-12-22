# tennis/utils.py
import random
from collections import Counter, defaultdict
from typing import List, Dict, Any


def _assert_all_int_ep_ids(ep_ids: List[Any]) -> List[int]:
    """
    このプロジェクトでは schedule 内の team1/team2/rests は ep_id(int) 統一。
    文字列が混ざったら（不明）表示の温床なので即エラーにする。
    """
    out = []
    for x in ep_ids:
        if isinstance(x, bool) or not isinstance(x, int):
            raise ValueError(f"[SCHEDULE] ep_id must be int, got {x!r} ({type(x)})")
        out.append(x)
    return out


def generate_singles_schedule(ep_ids: List[int], num_rounds: int, num_courts: int) -> List[Dict]:
    """
    シングルス用の“そこそこ公平な”乱数表生成（ep_id 専用）

    - 試合数が少ない人を優先してコートに出す
    - なるべく同じ組み合わせを避ける
    - 休憩が続いている人を優先してコートに出す
    - 余り/未割当は rests に入れる（試合は作らない）
    """
    players = _assert_all_int_ep_ids(list(ep_ids))
    n = len(players)
    if n < 2 or num_rounds <= 0 or num_courts <= 0:
        return []

    # 各人の試合数 / 連続休憩数
    match_count = {p: 0 for p in players}
    rest_streak = {p: 0 for p in players}

    # ペアごとの対戦回数
    pair_count = defaultdict(int)

    schedule: List[Dict] = []

    for r in range(1, num_rounds + 1):
        # 試合数が少ない & 休憩が続いている人を優先（同条件はランダム）
        order = players[:]
        random.shuffle(order)
        order.sort(key=lambda p: (match_count[p], -rest_streak[p]))

        available = order[:]
        matches = []

        max_matches_this_round = min(num_courts, n // 2)

        while len(matches) < max_matches_this_round and len(available) >= 2:
            p1 = available.pop(0)

            # p1 の相手候補：対戦回数が少ない & 試合数が少ない人を優先
            candidates = available[:]
            candidates.sort(
                key=lambda p: (
                    pair_count[frozenset({p1, p})],
                    match_count[p],
                    random.random(),
                )
            )

            p2 = candidates[0]
            available.remove(p2)

            matches.append(
                {
                    "court": len(matches) + 1,
                    "team1": [p1],
                    "team2": [p2],
                    "score1": None,
                    "score2": None,
                }
            )

            match_count[p1] += 1
            match_count[p2] += 1
            rest_streak[p1] = 0
            rest_streak[p2] = 0
            pair_count[frozenset({p1, p2})] += 1

        # playing / rests を確定
        playing = set()
        for m in matches:
            playing.update(m["team1"])
            playing.update(m["team2"])

        rests = [p for p in players if p not in playing]

        # 休憩 streak 更新
        for p in players:
            if p in playing:
                rest_streak[p] = 0
            else:
                rest_streak[p] += 1

        schedule.append(
            {
                "round": r,
                "matches": matches,  # 人数不足なら [] のまま → テンプレがメッセージ表示
                "rests": rests,
            }
        )

    return schedule


def generate_doubles_schedule(ep_ids: List[int], num_rounds: int, num_courts: int) -> List[Dict]:
    """
    ダブルス乱数表生成（ep_id 専用）

    方針は元のまま：
      1) 休憩メンバーを決定（休憩回数の偏りを減らし、連続休憩を避ける）
      2) ペア分け（同じペアの再発防止）
      3) ペア同士の対戦（過去対戦が少ない組み合わせ優先）

    追加の確定ルール：
      - 4人揃う試合だけ作る（足りない試合は作らない）
      - 余り（奇数人数/奇数ペア）は “捨てる” のではなく rests に入れる
      - schedule の値は ep_id(int) のみ
    """
    names = _assert_all_int_ep_ids(list(ep_ids))
    if len(names) < 4 or num_rounds <= 0 or num_courts <= 0:
        return []

    # 「誰と何回ペアを組んだか」
    pair_counts: Counter = Counter()
    # 「誰と何回対戦したか」
    vs_counts: Counter = Counter()
    # 「何回休憩したか」
    rest_counts: Counter = Counter()
    # 「最後に休憩したラウンド」
    last_rest_round = {n: None for n in names}

    schedule: List[Dict] = []

    for r in range(1, num_rounds + 1):
        max_players = num_courts * 4

        # ----- 1) 今ラウンドのプレイ／休憩を決める -----
        if len(names) <= max_players:
            playing = list(names)
            resting = []
        else:
            need_rest = len(names) - max_players

            scored = []
            for n in names:
                score = (
                    rest_counts[n],                        # 少ないほど「今回休ませる」優先（偏りを減らす）
                    1 if last_rest_round[n] == r - 1 else 0,  # 直前休憩はペナルティ（連続休憩回避）
                    random.random(),
                )
                scored.append((score, n))

            scored.sort()
            resting = [n for _, n in scored[:need_rest]]
            playing = [n for n in names if n not in resting]

        # 休憩情報更新
        for n in resting:
            rest_counts[n] += 1
            last_rest_round[n] = r

        # 4人未満なら試合なし（rests に全員）
        if len(playing) < 4:
            schedule.append({"round": r, "matches": [], "rests": list(names)})
            continue

        # ----- 2) ペア分け -----
        players_set = set(playing)
        pairs = []

        # もし奇数なら 1人余る → rests に回す（捨てない）
        leftover_single = None
        if len(players_set) % 2 == 1:
            # “休憩が続いている人”を優先して出す思想を崩さないため、
            # 余りはランダムに 1人引いて rests へ回す（ここは運用上大差が出にくい）
            leftover_single = players_set.pop()

        while len(players_set) >= 2:
            a = players_set.pop()
            candidates = list(players_set)
            random.shuffle(candidates)

            best_partner = None
            best_score = None
            for b in candidates:
                key = tuple(sorted((a, b)))
                score = pair_counts[key]  # 過去に組んだ回数（少ないほど良い）
                if best_score is None or score < best_score:
                    best_score = score
                    best_partner = b

            if best_partner is None:
                break

            players_set.remove(best_partner)
            pairs.append((a, best_partner))
            pair_counts[tuple(sorted((a, best_partner)))] += 1

        # ペアが 0 なら試合無し
        if not pairs:
            rests = list(names)
            schedule.append({"round": r, "matches": [], "rests": rests})
            continue

        # 奇数ペアなら最後のペアを “捨てずに” rests に回す
        extra_pair_players = []
        if len(pairs) % 2 == 1:
            a, b = pairs.pop()
            extra_pair_players.extend([a, b])

        # ----- 3) ペア同士の対戦カード -----
        matches = []
        num_pairs = len(pairs)

        idxs = list(range(num_pairs))
        best_arrangement = None
        best_score = None

        for _ in range(40):
            random.shuffle(idxs)
            ok = True
            score = 0

            for i in range(0, num_pairs, 2):
                p1 = pairs[idxs[i]]
                p2 = pairs[idxs[i + 1]]

                if set(p1) & set(p2):
                    ok = False
                    break

                for x in p1:
                    for y in p2:
                        key = tuple(sorted((x, y)))
                        score += vs_counts[key]

            if not ok:
                continue

            if best_arrangement is None or score < best_score:
                best_arrangement = idxs[:]
                best_score = score
                if score == 0:
                    break

        if best_arrangement is None:
            best_arrangement = list(range(num_pairs))

        for i in range(0, num_pairs, 2):
            p1 = pairs[best_arrangement[i]]
            p2 = pairs[best_arrangement[i + 1]]

            matches.append(
                {
                    "court": i // 2 + 1,
                    "team1": [p1[0], p1[1]],
                    "team2": [p2[0], p2[1]],
                    "score1": None,
                    "score2": None,
                }
            )

            for x in p1:
                for y in p2:
                    vs_counts[tuple(sorted((x, y)))] += 1

        # rests をまとめる（1) resting + 2)余り1人 + 2)余りペア
        rests = list(resting)
        if leftover_single is not None:
            rests.append(leftover_single)
        rests.extend(extra_pair_players)

        schedule.append({"round": r, "matches": matches, "rests": rests})

    return schedule
