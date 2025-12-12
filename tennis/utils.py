# tennis/utils.py
import random
from collections import Counter, defaultdict
from typing import List, Dict


def generate_singles_schedule(names, num_rounds, num_courts):
    """
    シングルス用の“そこそこ公平な”乱数表生成

    - 試合数が少ない人を優先してコートに出す
    - なるべく同じ組み合わせを避ける
    - 休憩が続いている人を優先してコートに出す
    """
    players = list(names)
    n = len(players)
    if n < 2:
        return []

    # 各人の試合数 / 連続休憩数
    match_count = {p: 0 for p in players}
    rest_streak = {p: 0 for p in players}

    # ペアごとの対戦回数
    pair_count = defaultdict(int)

    schedule = []

    for r in range(1, num_rounds + 1):
        # ─ ラウンドごとの並び順決定 ─
        #   試合数が少ない & 休憩が続いている人を優先
        order = players[:]
        random.shuffle(order)  # 同じ条件のときのランダム性
        order.sort(key=lambda p: (match_count[p], -rest_streak[p]))

        available = order[:]  # このラウンドでまだ割り当てていない人
        matches = []

        max_matches_this_round = min(num_courts, n // 2)

        # ─ コートにプレイヤーを割り当て ─
        while len(matches) < max_matches_this_round and len(available) >= 2:
            p1 = available.pop(0)

            # p1 と組ませる候補を決める
            candidates = available[:]
            # 1) まだ当たっていない or 対戦回数が少ない
            # 2) これまでの試合数が少ない
            candidates.sort(
                key=lambda p: (
                    pair_count[frozenset({p1, p})],
                    match_count[p],
                )
            )

            p2 = candidates[0]
            available.remove(p2)

            matches.append(
                {
                    "court": len(matches) + 1,
                    "team1": [p1],
                    "team2": [p2],
                }
            )

            match_count[p1] += 1
            match_count[p2] += 1
            rest_streak[p1] = 0
            rest_streak[p2] = 0
            pair_count[frozenset({p1, p2})] += 1

        # ─ 出場しなかった人の休憩カウント ─
        playing = set()
        for m in matches:
            playing.update(m["team1"])
            playing.update(m["team2"])

        for p in players:
            if p in playing:
                rest_streak[p] = 0
            else:
                rest_streak[p] += 1

        schedule.append(
            {
                "round": r,
                "matches": matches,
            }
        )

    return schedule


def generate_doubles_schedule(
    names: List[str],
    num_rounds: int,
    num_courts: int,
) -> List[Dict]:
    """
    テニスベア系の思想を取り入れたダブルス乱数表生成

    ■ ロジック方針（レベル考慮なし版）
      - 各ラウンドごとに
        1) 休憩メンバーを決定
           - 休憩回数が少ない人を優先的に休ませる（全体のバランスを取る）
           - 直前ラウンドで休憩した人は、できるだけ連続休憩にしない
        2) プレイヤーをペア分け
           - 過去に同じペアを組んだ回数が少ない相手を優先
        3) ペア同士をマッチング（対戦カード）
           - 過去に対戦した回数が少ないペア同士の組み合わせを優先
    """
    names = list(names)

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
            # 全員出場
            playing = list(names)
            resting = []
        else:
            need_rest = len(names) - max_players

            # 休憩候補にスコアを付ける
            #  - 休憩回数が少ない人を優先して休ませる
            #  - 直前ラウンドで休んだ人はスコアを悪くする（連続休憩を避ける）
            scored = []
            for n in names:
                score = (
                    rest_counts[n],                       # 少ないほど休ませたい
                    1 if last_rest_round[n] == r - 1 else 0,  # 直前休憩ならペナルティ
                    random.random(),                      # 同点時のランダマイザ
                )
                scored.append((score, n))

            scored.sort()
            resting = [n for _, n in scored[:need_rest]]
            playing = [n for n in names if n not in resting]

        # 休憩情報を更新
        for n in resting:
            rest_counts[n] += 1
            last_rest_round[n] = r

        # ----- 2) ペア分け（同じペアの再発防止を優先） -----
        players_set = set(playing)
        pairs = []

        while len(players_set) >= 2:
            # 適当に 1 人取り出す
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

        # ペアが 0 ならこのラウンドは試合無し
        if not pairs:
            schedule.append({"round": r, "matches": []})
            continue

        num_pairs = len(pairs)
        if num_pairs % 2 != 0:
            # 余りペアが出た場合は最後のペアを捨ててしまう（簡易対応）
            # ※ 実運用では「補欠・休憩扱い」にしても良い
            pairs = pairs[:-1]
            num_pairs = len(pairs)

        # ----- 3) ペア同士の対戦カードを決める -----
        matches = []
        idxs = list(range(num_pairs))
        best_arrangement = None
        best_score = None

        # 何通りかシャッフルして「対戦回数の少ない組合せ」を探る
        for _ in range(40):
            random.shuffle(idxs)
            ok = True
            score = 0

            for i in range(0, num_pairs, 2):
                p1 = pairs[idxs[i]]
                p2 = pairs[idxs[i + 1]]

                # 万一被りがあれば不採用
                if set(p1) & set(p2):
                    ok = False
                    break

                # 対戦回数の合計スコア
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
                    # これ以上良いものはないので打ち切ってもよい
                    break

        # どれも条件を満たさなかった場合はそのまま
        if best_arrangement is None:
            best_arrangement = list(range(num_pairs))

        # 最終的な対戦カードを生成
        for i in range(0, num_pairs, 2):
            p1 = pairs[best_arrangement[i]]
            p2 = pairs[best_arrangement[i + 1]]

            match = {
                "court": i // 2 + 1,
                "team1": [p1[0], p1[1]],
                "team2": [p2[0], p2[1]],
            }
            matches.append(match)

            # 対戦履歴を更新
            for x in p1:
                for y in p2:
                    vs_counts[tuple(sorted((x, y)))] += 1

        schedule.append({
            "round": r,
            "matches": matches,
        })

    return schedule
