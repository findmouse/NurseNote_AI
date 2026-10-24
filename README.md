# NurseNote AI

生成 AI を活用した **看護記録（SOAP）・退院サマリー作成支援システム**。

看護師はバイタル値・チェック項目・短い自由記述だけを入力する。システムが過去の看護記録と入院時情報を参照し、規定の様式で記録案を生成する。看護師が確認・修正して確定したものが正式な記録となる。

> [!IMPORTANT]
> 本システムは記録作成の **支援ツール** であり、記録内容の最終責任は看護師にあります。
> 生成物は下書きであり、看護師が確定するまで正式な記録として扱いません。
> 本リポジトリのシードデータはすべて **架空** の人物・架空の経過です。実在の患者データは一切含みません。

---

## 設計上の核

医療文書は法的証拠となる文書であり、AI が事実を創作することは許されない。
一方で SOAP の A（アセスメント）は定義上、事実ではなく事実に基づく臨床的解釈であるため、
「AI は推測してはならない」という単純な禁止では設計が成立しない。

本システムが採るのは禁止ではなく **区別** である。

- **生成文のすべての記述に `source_type` を持たせ、事実と解釈を混ぜない**
  （`today_input` / `historical_note` / `patient_profile` / `clinical_inference`）
- **数値は LLM に生成させない。** バイタル値はテンプレートで直接埋め込む
- **検証は 2 層。** 数値・日付・患者の一致は LLM に判定させず Python / SQL で決定的に検証する
- **外部 LLM へは許可リスト DTO で最小化した情報のみ送る。** 院内運用ではローカル LLM を既定とする

詳細な根拠と実装方針は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) にある。

---

## 動かす

```bash
docker compose up -d --build
```

| URL | 内容 |
|---|---|
| http://localhost:5173 | アプリケーション画面 |
| http://localhost:9200/docs | Swagger UI（API 仕様） |
| http://localhost:9200/api/v1/health | ヘルスチェック |

起動時に `alembic upgrade head` → `python -m app.seed` → `uvicorn` が順に実行される。
シードは冪等（投入済みならスキップ）。再投入は `python -m app.seed --force`。

停止は `docker compose down`（データは残る）、DB ごと初期化は `docker compose down -v`。

### デモ用アカウント

パスワードはすべて `nurse1234`。

| 職員番号 | 氏名 | 所属 | 権限 |
|---|---|---|---|
| N001 | 山田 花子 | 3F東病棟 | nurse |
| N002 | 佐藤 美咲 | 3F東病棟 | nurse |
| N003 | 高橋 健一 | 4F西病棟 | nurse |
| A001 | 管理 太郎 | 管理部 | admin（全病棟参照可） |

看護師は **自分の所属病棟の入院患者しか参照できない**（admin は全病棟可）。
N001 でログインして 4F西病棟の患者 ID を直接叩くと 403 が返る、という挙動の確認に使える。

---

## 開発環境（Docker を使わない場合）

conda 環境名は `nursenote`。Python は **3.12**（`backend/Dockerfile` の `python:3.12-slim` に合わせている）。

```bash
conda create -y -n nursenote python=3.12
conda activate nursenote
pip install -r backend/requirements.txt -r backend/requirements-llm.txt
```

依存は 2 ファイルに分かれている。

| ファイル | 内容 | 用途 |
|---|---|---|
| `backend/requirements.txt` | FastAPI / SQLAlchemy / Alembic / JWT | M1 の API を動かすだけならこれで足りる |
| `backend/requirements-llm.txt` | LangChain 1.2 系 / LLM プロバイダ / pgvector | M2 以降。依存が重いので分離した |

LangChain は **1.2 系に固定** している。1.0 で導入された middleware
（`PIIMiddleware` / `SummarizationMiddleware` / `wrap_model_call` など）を使うため、0.3 系には戻さない。

DB だけ Docker で起動して API はローカルで動かす場合：

```bash
docker compose up -d db
```

---

## ディレクトリ構成

```
NurseNote_AI/
├─ backend/                  FastAPI
│  ├─ app/
│  │  ├─ main.py             エントリポイント
│  │  ├─ api/
│  │  │  ├─ deps.py          認証・病棟権限チェック（Depends）
│  │  │  └─ v1/              auth / patients / admissions / notes
│  │  ├─ core/               設定・パスワードハッシュ・JWT
│  │  ├─ db/                 エンジンと非同期セッション
│  │  ├─ models/             SQLAlchemy モデル
│  │  ├─ schemas/            Pydantic スキーマ（API の入出力）
│  │  └─ seed.py             架空のシードデータ
│  └─ alembic/versions/      マイグレーション
├─ frontend/
│  ├─ html/                  index.html / app.js / style.css
│  └─ nginx.conf             静的配信 + /api のリバースプロキシ
├─ docs/ARCHITECTURE.md      アーキテクチャ設計書
└─ docker-compose.yml        db / backend / frontend
```

**フロントエンドにビルド工程は無い。** CDN から Vue 3 を読み込み、HTTP はブラウザ標準の
`fetch` を使う。npm も node_modules も存在しない。5173 は Vite ではなく nginx である。

データは **患者 → 入院（admission）→ 看護記録** の 3 階層。
患者は入院・外来を問わず **カルテ番号**（`karte_no`）で識別する。番号は患者マスタにあり、入院には持たせない。
看護記録は `admission_id` に紐づく。病棟は二交代（日勤・夜勤）で、同じ日に勤務帯ごとに 1 件、計 2 件。

---

## 技術スタック

| 層 | 採用 | 理由 |
|---|---|---|
| フロントエンド | Vue 3（CDN・ビルド不要） | 画面が単一で、ビルド工程を持つ利点が無い |
| バックエンド | FastAPI | 非同期対応、OpenAPI 自動生成、LLM ストリーミングとの相性 |
| DB | PostgreSQL 16 + pgvector | JSONB と全文検索、Few-shot 事例のベクトル検索 |
| バリデーション | Pydantic v2 | LangChain の構造化出力と同じ仕組みを使える |
| LLM 層 | LangChain 1.2 | middleware で PII 検出・要約・リトライを段として差し込める |
| LLM | 既定 Ollama（院内）／任意 DeepSeek・Qwen | 患者情報を外へ出さないことを既定にする |
| 認証 | JWT（PyJWT）+ bcrypt | |

---

## 開発状況

| # | 内容 | 状態 |
|---|---|---|
| **M1** | Docker 構成、DB スキーマ、Alembic、シードデータ、ログイン（JWT）、患者検索、過去記録表示、新規入院登録・退院処理 | ✅ 完了 |
| **M2** | Chain A による記録生成、型付き根拠出力（`EvidenceItem`）、許可リスト DTO、SSE ストリーミング、編集・確定保存、監査ログ | ✅ 完了 |
| **M3** | 検証 Layer 1（決定的チェック）、Chain B による Layer 2、確定制御、記録様式の切り替え、LangSmith 評価セット | 未着手 |
| **M4** | 退院サマリー（Map-Reduce）、入院時情報の入力フォーム | 未着手 |

画面上の「記録を生成」「確定して保存」は M2 で動作する。退院サマリーは M4。
クラウド LLM の API キーは未設定。使うときは `DEEPSEEK_API_KEY` または `QWEN_API_KEY` を入れ、`ALLOW_CLOUD_LLM=true` と `LLM_PROVIDER` を切り替える。既定は Ollama。

---

## ドキュメント

| ファイル | 役割 |
|---|---|
| `README.md`（本ファイル） | **動かし方と現状。** 何であるか、どう起動するか、どこに何があるか |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **なぜそう作るか。** 幻覚対策の設計根拠、LangChain のチェーン構成、検証の 2 層設計、外部送信の最小化、評価方針 |

---

## 注意事項

安全性・プライバシーに関する制約は [docs/ARCHITECTURE.md §9](docs/ARCHITECTURE.md) に全 10 項目がある。
特に重要なもの：

1. **実在の患者データは投入しない。** 開発・デモにはシードデータ（架空）のみを使う
2. **外部 LLM とトレース基盤には同じ規約を適用する。** プロンプト全文が LangSmith へ送られるため例外を作らない
3. **クラウド LLM は明示的な許可を要する。** `ALLOW_CLOUD_LLM` の既定値は `false`。
   設定を忘れた場合に起きるのは「ローカルで動く」であって「気づかずクラウドへ送信する」ではない
4. `docker-compose.yml` の `JWT_SECRET` と DB パスワードは **開発用の固定値** である。
   本番では必ず差し替える

`.env` は Git 管理外。API キーをコードに直接書かないこと。

---

## ライセンス

[MIT](LICENSE)
