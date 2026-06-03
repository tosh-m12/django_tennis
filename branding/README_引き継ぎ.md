# Deuce Net ブランド／ロゴ 引き継ぎ（VS Code側・実装用）

このフォルダ（`django_tennis/branding/`）は、マーケ側で確定したブランド資産の受け渡し用です。
元データ・検討経緯は `…/projects/side/tennis_marketing/06_ロゴ案/`（`final/` が確定版）。

---

## 1. 確定ブランド仕様
- **名称**：**Deuce Net**（読み：デュースネット。洒落表記 `Deuce.Net`）
- **ロゴ表記**：`Deuce 🎾 Net`（"."の位置に本物のテニスボール絵文字）
- **アイコン**：頭文字モノグラム **`D🎾N`**
- **書体**：**Optima**（Bold相当・letter-spacing 約 -0.5〜-1）
- **文字色**：濃紺 **#15243F**
- **ボール**：本物の絵文字 🎾（PNGには Apple版を焼き込み済み）
- **アプリのモード色（既存 base.css の `--accent`）**：一般＝`#3B82F6` ／ 幹事＝`#F87171`、バー＝`.topbar{background:var(--accent)}`
- **トップバー上のルール**：ロゴ文字＝濃紺 #15243F／ハンバーガー＝白／「幹事モード」等のテキストバッジは付けない

## 2. 同梱アセット
- `png/` … `icon_navy.png`(1024) / `icon_navy_512` / `icon_navy_192` / `apple-touch-icon.png`(180) / `favicon_32.png` / `favicon_16.png` / `icon_light.png` / `wordmark.png`(濃紺・透過) / `bar_blue.png` / `bar_red.png` / `lockup.png`
- `svg/` … `logo_master.svg` / `logo_on_blue_bar.svg` / `logo_on_red_bar.svg` / `logo_lockup.svg`
  - ※ **ボールの扱いが2系統**：**PNG＝本物のApple絵文字🎾を焼き込み**（ブランド確定の見た目）／**SVG＝ボールをベクターで再現**（絵文字はSVGに確実に埋め込めないため）。見た目重視は**PNGを正**とする。
  - ※ SVGの文字は Optima 前提（Apple環境向け）。クロスプラットフォームで同一表示にするなら **PNG** を使うのが安全。

## 3. 実装TODO（推奨手順）

### (A) favicon / アプリアイコン
1. `branding/png/favicon_32.png`, `favicon_16.png`, `apple-touch-icon.png` を `tennis/static/tennis/` にコピー。
2. `templates/tennis/base.html` の `<head>` に追加：
   ```html
   {% load static %}
   <link rel="icon" type="image/png" sizes="32x32" href="{% static 'tennis/favicon_32.png' %}">
   <link rel="icon" type="image/png" sizes="16x16" href="{% static 'tennis/favicon_16.png' %}">
   <link rel="apple-touch-icon" sizes="180x180" href="{% static 'tennis/apple-touch-icon.png' %}">
   ```

### (B) トップバーのロゴ（重要：クロスプラットフォーム対策）
メンバーはAndroid/Windowsの微信ブラウザ等で開くため **Optimaは入っていない**。バーのロゴは**画像で出す**のが確実（絵文字もApple版で固定される）。
1. `branding/png/wordmark.png`（濃紺・透過）を `tennis/static/tennis/wordmark.png` にコピー。
2. `base.html` の `.topbar` 内タイトル（現状 `Deuce Net` テキスト＋`- 幹事モード`バッジ）を画像に差し替え：
   ```html
   <a class="topbar-title" href="...">
     <img src="{% static 'tennis/wordmark.png' %}" alt="Deuce Net" class="topbar-logo">
   </a>
   ```
   ```css
   .topbar-logo{ height:26px; width:auto; display:block; }   /* バー高さに合わせ調整 */
   ```
3. 透過PNGの濃紺ワードマークは **青バー・赤バー両方**に乗る（モード分岐不要）。ハンバーガーは白のまま。
   - `- 幹事モード` の文字バッジは**削除**（仕様）。モード判別は赤/青のバー色で行う。
   - ※ 文字も含めてベクターにしたい場合は `svg/logo_master.svg`（Optima依存）か、後日アウトライン化版に差し替え。

### (C) （任意）PWA/マニフェスト
`icon_navy_192.png` / `icon_navy_512.png` を `site.webmanifest` の icons に登録。

## 4. 未確定・要相談
- ドメイン：`deucenet.com` / `deucenet.app` が空き（`deuce.net`単体は他者所有）。取得はトシ側で。
- 商標：J-PlatPat（区分9・42）で Deuce 類似の最終確認（継続）。
- Optima の最終アウトライン化（完全な環境非依存にするなら）。

> 連絡：このブランド方針はマーケ側メモリ（project-tennis-app-marketing）にも記録済み。意味の伝わらない旧タグライン「コートのネット、仲間のネットワーク。」は**不採用**。
