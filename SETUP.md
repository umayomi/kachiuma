# セットアップ手順（スマホだけでOK）

初回だけ手を動かします。以降の開発は「INDEX.md を読んで」で回ります。

## 1. GitHub にリポジトリを作る（公開）
1. GitHub アプリ or Safari で github.com を開く
2. 右上「＋」→ **New repository**
3. 名前: `kachiuma` ／ **Public** を選択 ／ Create

## 2. このキットをアップロード
- 配布 zip を iPhone の「ファイル」アプリで解凍
- GitHub のリポジトリ画面 → **Add file → Upload files** → 解凍したフォルダの中身を選択 → Commit
  （フォルダ構造ごとアップロードできます。`.github` フォルダも忘れずに）
- アップロード後、`INDEX.md` 内の `<your-username>/kachiuma` を自分のに書き換え（鉛筆アイコンで編集）

## 3. Vercel に接続（無料・初回のみ）
1. vercel.com に GitHub アカウントでログイン
2. **Add New → Project** → `kachiuma` を Import
3. Framework Preset: **Other**（そのままでOK。`vercel.json` が効きます）
4. Deploy → 数十秒で公開URLが出る → スマホで開くとサンプル画面が表示される

## 4. 自動実行を有効化
- リポジトリの **Actions** タブ → ワークフローを Enable
- 手動テスト: Actions → `collect-and-analyze` → **Run workflow**（日付は空でOK）

> 現状は収集が雛形（空）なので、画面はサンプル表示のままです。
> 次の開発（Phase 1）で実データ収集を実装すると、本番予想に切り替わります。

## 5. 開発を進める
AI に **「INDEX.md を読んで」** と伝える → 次のタスク提案 → 「承認します」で実装。
生成されたコードを GitHub アプリでコミットすれば、Actions が回ってサイトが更新されます。

---

### 補足: 無料の範囲
- 公開リポジトリの GitHub Actions は標準ランナー無料無制限
- Vercel の個人利用は無料枠で十分
- 生の netkeiba データはコミットしない設定（`.gitignore`）
