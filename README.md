# プログラム編成システム

`abstract.xlsx` の1枚目にある演題一覧を読み込み、Django 管理画面でプログラムを編成します。

## GitHub Release の発行

リリース対象のコミットにバージョンタグを付け、GitHubへpushします。

```bash
git tag -a v1.0.0 -m 'Release v1.0.0'
git push origin v1.0.0
```

GitHub Actionsの `Release` workflowがタグの形式を確認し、GitHub Releaseを公開します。リリースノートはGitHubが自動生成し、ソースコードのZIP / tar.gzはGitHub標準のダウンロードを使用します。DBやアップロード済みPDFは含みません。追加のシークレット登録は不要で、公開ジョブだけに `GITHUB_TOKEN` の `contents: write` 権限を付与しています。

タグは `v1.0.0` の形式を使用します。`v1.0.0-rc.1` などハイフン付きのタグはプレリリースとして公開します。手動実行する場合は、Actions → Release → Run workflowで対象の**タグ**を選択してください（ブランチを選ぶとエラーになります）。workflowを手動実行するには、このファイルがデフォルトブランチにも必要です。公開済みの同じタグで再実行してもReleaseは変更しません。

## 起動

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

管理画面は `http://127.0.0.1:8000/admin/`、公開タイムテーブルの年会一覧は `http://127.0.0.1:8000/`、編成画面の年会一覧は `http://127.0.0.1:8000/organize/` です。編成画面はログインと対応する権限が必要です。

## 本番環境の PostgreSQL

開発時は設定なしで従来の `db.sqlite3` を使用します。本番では `.env.example` を参考に、アプリの実行環境へ次の変数を設定してください（`.env` の自動読み込みはありません）。

```bash
export DJANGO_SETTINGS_MODULE=config.settings.production
export PROGRAM_DEBUG=0
export PROGRAM_SECRET_KEY='50文字以上のランダムな秘密鍵に置き換えてください'
export PROGRAM_ALLOWED_HOSTS=program.example.com
export PROGRAM_DB_ENGINE=postgresql
export PROGRAM_DB_NAME=program_org
export PROGRAM_DB_USER=program_org
export PROGRAM_DB_PASSWORD='DBユーザーのパスワード'
export PROGRAM_DB_HOST=127.0.0.1
export PROGRAM_DB_PORT=5432
```

DB管理者が、ログイン可能な専用ロール `program_org` と、そのロールを所有者とする UTF-8 のデータベース `program_org` を事前に作成します。アプリのロールにスーパーユーザー権限は不要です。リモートDBへ証明書検証付きTLS接続を行う場合は `PROGRAM_DB_SSLMODE=verify-full`、必要に応じて `PROGRAM_DB_SSLROOTCERT` にCA証明書のパスを指定します。ローカルのUnixソケット認証では `PROGRAM_DB_HOST=''` としてパスワードを省略できます。

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy
```

新規DBの場合は上記で初期化します。既存データを移行する場合は下の手順を使ってください。接続失敗時や不正なDB種別指定時にSQLiteへ自動切り替えはしません。`PROGRAM_DB_ENGINE` の値は `sqlite` または `postgresql` です。SQLiteの保存先も `PROGRAM_DB_NAME` で指定できます。

本番のアプリ起動にはGunicorn等のWSGIサーバーを使用し、HTTPS、静的ファイル配信、セキュアCookie等をデプロイ設定で構成してください。`check --deploy` の指摘は構成に合わせて解消してください。PostgreSQL対応ドライバーは [Djangoのデータベース仕様](https://docs.djangoproject.com/en/4.2/ref/databases/#postgresql-notes) に従い psycopg 3 を使用しています。

### 本番設定モジュール

`DJANGO_SETTINGS_MODULE=config.settings.production` を管理コマンドとGunicornの両方に設定します。共通設定は `config/settings/base.py`、開発用は `config.settings.development` にあります。従来の `config.settings` も開発用として使用できます。

本番では `PROGRAM_DEBUG` に関係なく `DEBUG=False` となり、50文字以上の秘密鍵と明示的な `PROGRAM_ALLOWED_HOSTS` が必須です。秘密鍵は `.venv/bin/python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'` で生成できます。生成した値を安全に環境変数へ保存してください。DB種別を省略するとPostgreSQLを使用し、DB名とユーザー名も必須です。移行元を読む場合に限り `PROGRAM_DB_ENGINE=sqlite` と保存先を明示できます。

HTTPSリダイレクト、セキュアCookie、HSTS（初期値3600秒）が有効です。HSTSの調整には `PROGRAM_SECURE_HSTS_SECONDS`、全サブドメインへの適用とpreloadには `PROGRAM_SECURE_HSTS_INCLUDE_SUBDOMAINS=1`、`PROGRAM_SECURE_HSTS_PRELOAD=1` を使用します。後二者は初期値では無効です。リバースプロキシが `X-Forwarded-Proto` を必ず上書きし、Djangoへの直接アクセスを制限した環境では `PROGRAM_TRUST_PROXY_SSL_HEADER=1` を指定します。TLS終端プロキシでこの設定を省略するとリダイレクトが繰り返されます。

必要な信頼済みオリジンは `PROGRAM_CSRF_TRUSTED_ORIGINS=https://program.example.com` のようにカンマ区切りで指定します。静的ファイルとメディアの保存先は `PROGRAM_STATIC_ROOT`、`PROGRAM_MEDIA_ROOT` で変更できます。原稿用の `PROCEEDINGS_ROOT` は未指定時に `MEDIA_ROOT` を使用します。本番メール送信の初期値はSMTPです。

```bash
# 上記の秘密鍵・ホスト・DB設定も同じ実行環境へ設定してから実行
export DJANGO_SETTINGS_MODULE=config.settings.production
.venv/bin/python manage.py check --deploy
.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 360
```

設定項目の背景は [Djangoのデプロイチェックリスト](https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/) を参照してください。

### SQLiteから既存データを移行

1. アプリとDBへの書き込みを停止し、SQLiteファイルと原稿PDF・公開PDFをバックアップします。移行・確認が完了するまで停止を維持します。
2. **移行元のSQLite設定のまま**、最新のマイグレーションを適用して全データを出力します。出力先はアクセスを制限したバックアップ用ディレクトリを指定してください。

   ```bash
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py dumpdata --all --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --indent 2 --output /secure/backup/program-data.json
   ```

3. 上記のPostgreSQL環境変数へ切り替え、**新規の空のDB**へ取り込みます。先に `createsuperuser` は実行しません。ユーザー・権限・編成データも移行対象です。

   ```bash
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py loaddata /secure/backup/program-data.json
   .venv/bin/python manage.py check
   ```

4. 年会・演題・著者の件数、ログインと権限、取り消し演題、番号・並び順、Excel出力を確認します。原稿ファイルはDBダンプに含まれないため、保存先を変更する場合は相対パスを維持して別途コピーします。確認後、PostgreSQL設定でサービスを再開します。JSONには個人情報やパスワードハッシュが含まれるので、確認後は安全に保管または削除してください。

失敗時はサービスを停止したまま移行先を調査し、必要ならバックアップ済みSQLiteの設定へ戻します。切り替え後にPostgreSQLへ書き込まれたデータはSQLiteへ自動反映されません。本番バックアップは `pg_dump` と原稿・公開PDFの両方を対象にしてください。

### Ansibleを使用する場合

`infra-ansible/roles/prog_gen` も同じ環境変数を使用します。インベントリで `prog_gen_db_engine: postgresql`、`prog_gen_db_name: program_org`、`prog_gen_db_user: program_org`、`prog_gen_db_password`、`prog_gen_db_host` を設定してください。パスワードはAnsible Vault等で管理します。TLS設定には `prog_gen_db_sslmode` と `prog_gen_db_sslrootcert` を使用します。ロールはDBやDBユーザーを作成しないため、事前に用意してください。既存環境への意図しない切り替えを避けるため、ロールの初期値は従来の共有ディレクトリ内のSQLiteです。データ移行は自動実行されません。

### DB別のテスト

`.venv/bin/python manage.py test` は現在のDB設定でテスト専用DBを作成します。PostgreSQLで実行する際は、本番と別の検証用ロール・DBを使用し、ロールにテストDB作成用の `CREATEDB` 権限を付与してください。

## 操作

1. 管理画面の「年会情報」で年会名、略称、会期の開始日・終了日、会場を登録します。URLには会期開始日の年を使い、2026年の年会なら編成画面は `/organize/2026/`、公開タイムテーブルは `/2026/` です。同じ年に2件の年会は登録できません。略称はURLには使いません。
2. 編成画面の「未割り当て」枠にあるインポートアイコン、または管理画面の「演題」→「アブストラクトをインポート」から `abstract.xlsx` をアップロードします。
3. 管理画面の「部屋」で、部屋名と所属する年会を登録します。同じ部屋名を別の年会で使えます。
4. `/organize/` の年会一覧から編成画面を開き、＋アイコンからポップアップでセッションを作成します。口頭発表は1講演あたりの時間（初期値20分）と講演数を指定し、その積を時間枠にします。講演数を超えて演題を割り当てることはできません。ポスター発表は時間枠の長さを指定し、演題数に制限はありません。施設報告ポスターは同じ年会の異なるポスターセッションを2つ選び、その両方の時間枠に演題を表示します。管理画面からもセッションを作成できます。
   既存セッションの発表形式は「その他・従来形式」のまま保持されます。新しい定員や時間枠のルールを適用する場合は、管理画面で発表形式と必要な枠情報を設定してください。
   年会が未設定の既存セッションがある場合は、年会一覧の「年会未設定のセッション」から確認できます。年会への割り当ては管理画面で行います。
5. 未割り当ての演題カードをセッションの枠へドラッグします。枠内で並び替えたり、未割り当てへ戻したりできます。移動ごとに保存されます。
   セッションへ割り当てると第1希望が「カテゴリー」になります。第2希望を採用する場合は演題カードの鉛筆アイコンから「カテゴリー」を変更します。口頭発表セッションの「座長を編集」から、割り当て済み演題のカテゴリーごとに座長を登録できます。
   編成画面上部のインポートアイコンから `program.xlsx` をインポートできます。列は見出し名で判別するため、順序を入れ替えても取り込めます。演題登録番号を照合して、Excelのセッション名・開催日・発表時間・会場・講演番号・カテゴリー・座長を取り込みます。会期外の日付や重複した講演番号がある場合は取り込まず、エラーを表示します。既に同じ日時・部屋・名称のセッションがあれば再利用します。エクスポートアイコンを押し、ポップアップで XLSX 形式を選んで「ダウンロード」を押すと、同じ列構成で割り当て済み演題を書き出せます。書き出したファイルは再取り込みできます。
   参考の `program.xlsx` は2026年8月26〜28日の内容です。取り込み先の年会の会期をこの期間に設定してからインポートしてください。同じカテゴリーに複数の座長が記載されている場合は、座長欄に全員を併記します。
   セッションコードが `FRO` の場合、演題には並び順に `FRO01`、`FRO02`…というプログラム番号が自動で付きます。並び替え、移動、セッションコード変更では再採番され、発表取り消しだけでは番号を変更しません。セッションコードは重複できません。コードを設定していないセッションでは手動のプログラム番号を使えます。
   同じエクスポートのポップアップで JSON 形式を選ぶと JSON ファイルを保存できます。どちらの形式もファイル名の先頭に年会の略称（小文字）を付けます（例：`pasj2026_program.xlsx`、`pasj2026_program.json`）。対象年会の割り当て済み演題（発表取り消しを含む）を、従来の `pasj-tools/pasj_program_to_json.py` と同じ英語キー・`coauthors` 配列で出力します。日付は「8月26日」形式です。Excel 出力と同じ閲覧権限が必要です。出力用データの取得・組み立ては `program/program_data.py` で共通化し、`program/program_excel.py` と `program/program_json.py` がそれぞれ XLSX／JSON を生成します。JSON 出力時には XLSX を作成しません。
6. 「演題」で発表開始・終了時刻を設定します。セッションコードがない場合はプログラム番号を手動で設定できます。部屋はセッションの部屋を引き継ぎ、演題ごとに上書きできます。
7. 発表取り消しは演題の「状態」を変更します。セッションに割り当て済みの演題は、編成画面とタイムテーブルに取り消し線付きで残り、プログラム番号と講演時間も保持します。

`abstract.xlsx` の「年会賞への応募応募」は演題の「年会賞に応募」として取り込まれます。応募演題は編成カードに「年会賞応募」と表示され、演題の編集画面と管理画面ではチェックボックスで変更できます。

## 年会プログラムのPDF出力

編成画面のエクスポートアイコンから **PDF** を選んでダウンロードします。ファイル名は `pasj2026_program.pdf` のように年会略称を使います。XLSX／JSONと同じ閲覧権限が必要です。生成に時間がかかる場合は、ダウンロードが始まるまでお待ちください。

`pasj_program_builder/build_program.py` のプログラム集レイアウトを `program/program_print.py` に取り込みました。A4サイズでセッションごとに改ページし、開催日・曜日・時間帯・会場・座長・カテゴリー・講演番号・和英題目・登壇者を表示します。取り消し演題も番号を維持して取り消し線付きで掲載します。施設報告ポスターはXLSXと同じく両方の日付・時間帯を併記します。対象は割り当て済み演題で、演題のない休憩枠などは掲載しません。著者索引は含みません。

`program/program_pdf.py` が共通の出力データからHTML/CSSを生成し、Vivliostyle CLIでPDFに変換します。JSONファイルの手動保存は不要で、参考コードのディレクトリにも実行時には依存しません。リクエストごとに一時ディレクトリを作成し、終了時に中間ファイルとPDFを削除します。演題がない場合や生成に失敗した場合は編成画面にエラーを表示します。

### AlmaLinux 9へのデプロイ（PDF生成環境を含む）

以下はAlmaLinux 9用の手順です。アプリを実行する一般ユーザーでプロジェクトを配置し、OSパッケージの導入だけを管理者権限で行います。既存環境を更新する場合は、先にDBと `PROCEEDINGS_ROOT` のバックアップを取ってください。

#### 1. CRB・フォント・ブラウザの依存ライブラリ

**フォントの導入前にCRBリポジトリを有効化してください。** 今回のAlmaLinux 9環境ではCRBの有効化が必要でした。[AlmaLinux公式のリポジトリ説明](https://wiki.almalinux.org/repos/AlmaLinux)にも有効化コマンドが掲載されています。

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf install -y python3 python3-pip fontconfig \
  google-noto-sans-cjk-jp-fonts urw-base35-fonts \
  mesa-libgbm nss atk at-spi2-atk cups-libs libdrm \
  libXcomposite libXdamage libXfixes libXrandr libxkbcommon alsa-lib
fc-cache -f
fc-match "Noto Sans CJK JP"
fc-match "Nimbus Roman"
```

この環境で実際に導入された日本語フォントのパッケージ名は `google-noto-sans-cjk-jp-fonts` です。`fc-match` の結果がそれぞれ `NotoSansCJKjp-Regular.otf`、`NimbusRoman-Regular.otf` になることを確認します。DejaVu Sansなど別のフォントに置き換わっている場合は、PDFが生成できても日本語が「□」になることがあります。

#### 2. Node.js・Vivliostyle

Vivliostyle CLI 11系にはNode.js 22.12.0以上が必要です。[Vivliostyle公式手順](https://docs.vivliostyle.org/en/cli/getting-started/)を参照してください。今回確認した構成はNode.js **24.21.0**、Vivliostyle CLI **11.3.3**です。

対応するNode.jsが未導入なら、例えば[NodeSourceのRPM向け手順](https://www.nodesource.com/blog/Update-Node.js-versions-on-linux)でNode.js 24系を導入します。すでに対応版があればこの段階は省略できます。

```bash
curl -fsSL https://rpm.nodesource.com/setup_24.x -o /tmp/nodesource_setup_24.sh
# ダウンロードしたスクリプトを確認してから実行
sudo bash /tmp/nodesource_setup_24.sh
sudo dnf install -y nodejs
node --version
npm --version
sudo npm install --global @vivliostyle/cli@11.3.3
hash -r
command -v node
command -v vivliostyle
vivliostyle --version
```

WSLでもNode.jsとVivliostyleはLinux側に導入します。`command -v vivliostyle` が `/mnt/c/...` を指す場合はWindows側のインストールを参照しています。今回の実行パスは `/usr/bin/node` と `/usr/bin/vivliostyle` です。Windows側を参照すると `Cannot find module '@rolldown/binding-linux-x64-gnu'` などのエラーになります。

#### 3. Djangoの準備

プロジェクトのディレクトリで、アプリの実行ユーザーとして実行します。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install gunicorn
export PROGRAM_SECRET_KEY='環境ごとに生成した十分に長いランダムな秘密値に置換'
export DJANGO_SETTINGS_MODULE=config.settings.production
export PROGRAM_DEBUG=0
export PROGRAM_ALLOWED_HOSTS='program.example.jp'
export VIVLIOSTYLE_CLI=/usr/bin/vivliostyle
export PROGRAM_PDF_TIMEOUT=300
# 保存先を変更する場合は、実行ユーザーが書き込めるディレクトリを用意する
export PROCEEDINGS_ROOT=/data/proceedings
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py check --deploy
```

`createsuperuser` は初回のみ実行します。秘密値は `.venv/bin/python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'` で生成できます。このアプリは `.env` を自動では読み込みません。環境変数はシェル、または後述のsystemdの `EnvironmentFile` で渡します。

SQLiteの `db.sqlite3` とその親ディレクトリ、`PROCEEDINGS_ROOT`、実行ユーザーのホーム内のブラウザキャッシュ、一時ディレクトリに書き込み権限が必要です。`collectstatic` の出力先はプロジェクト直下の `staticfiles/` です。[Django公式の静的ファイル設定](https://docs.djangoproject.com/en/4.2/ref/settings/#static-root)に従い、Webサーバーから `/static/` として配信します。

#### 4. PDF生成の動作確認

初回はVivliostyleがブラウザをダウンロードする場合があります。ネットワークに接続できる状態で、**サービスと同じ一般ユーザー**として生成を試してください。rootでの生成やブラウザのサンドボックス無効化は不要です。

```bash
.venv/bin/python manage.py shell <<'PY'
from pathlib import Path
from program.models import AnnualMeeting
from program.program_pdf import export_program_pdf

meeting = AnnualMeeting.objects.get(start_date__year=2026)  # 対象年に変更
Path('/tmp/program-check.pdf').write_bytes(export_program_pdf(meeting))
PY
```

割り当て済み演題がある年会を指定してください。PDFを開き、日本語、英語、座長、改ページを確認します。エラー時はこのコマンドの例外に原因が表示されます。`listen EPERM` はローカルHTTPサーバー起動の制限、共有ライブラリ不足はブラウザ実行環境を確認してください。上記のパッケージに加えて不足が報告された場合は、そのライブラリを導入します。

#### 5. 本番プロセスの起動

本番ではGunicornを使います。[Django公式のGunicorn手順](https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/gunicorn/)に対応する起動例です。

```bash
.venv/bin/gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 --workers 2 --timeout 360
```

systemdで常駐させる場合の `/etc/systemd/system/program-org.service` の例です。`program` は専用の一般ユーザー、`/srv/program_org` はそのユーザーが管理する配置先の例です。実際のユーザー・パスに置き換えてください。

```ini
[Unit]
Description=Annual meeting program
After=network.target

[Service]
User=program
Group=program
WorkingDirectory=/srv/program_org
EnvironmentFile=/etc/program-org.env
Environment=PATH=/srv/program_org/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/srv/program_org/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 360
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`/etc/program-org.env` には手順3の環境変数を `名前=値` 形式で記載します（`export` は付けません）。root所有・権限600にして秘密値を保護します。`VIVLIOSTYLE_CLI` は `command -v vivliostyle` で確認したパスを指定します。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now program-org
sudo journalctl -u program-org -n 100
```

公開用WebサーバーでHTTPSを設定し、アプリへのリクエストは `127.0.0.1:8000` に転送してください。Nginxの場合は既存のHTTPS `server` ブロック内に次を設定します。ホスト名・証明書の設定は運用環境に合わせて用意します。

```nginx
client_max_body_size 100m;
location /static/ {
    alias /srv/program_org/staticfiles/;
}
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 360s;
}
```

アップロードサイズは複数PDFの合計に合わせて調整します。HTTPS終端後のスキーム認識が必要なため、信頼するプロキシが上記ヘッダーを必ず上書きする構成で、`config.settings.production` を使用して `PROGRAM_TRUST_PROXY_SSL_HEADER=1` を設定します。セキュアCookieは本番設定で有効になります。`check --deploy` の残りの指摘は運用環境に応じて確認します。

AlmaLinuxのSELinuxが有効な場合は、Nginxからのバックエンド接続と静的ファイルの読み取りを許可するポリシー・ファイルラベルを設定します。DB・`PROCEEDINGS_ROOT` はWebサーバーから直接配信しません。

環境変数 `VIVLIOSTYLE_CLI` で実行ファイルの絶対パスを指定できます（初期値 `vivliostyle`）。`PROGRAM_PDF_TIMEOUT` は生成の制限時間を秒で指定します（初期値 `300`、正の整数）。同期処理のため、Webサーバー・リバースプロキシのタイムアウトはこの値に起動・後処理の余裕を加えて設定してください。

更新時は、バックアップ後に依存パッケージ更新、`migrate`、`collectstatic --noinput`、`systemctl restart program-org` の順に実行し、ログイン・静的ファイル・PDFダウンロードを確認します。

## プロシーディングス

`/procgen/` で年会を選ぶと、`/procgen/2027/` のような年会別ページに、プログラムコード・題目・講演者・Status の表を表示します。未採番の演題も表示し、取り消し演題には取り消し線を付けます。閲覧・PDFのダウンロードにはログインと演題の閲覧権限、アップロードには追加で演題の変更権限が必要です。

PDFを複数選択するか、アップロード欄へまとめてドラッグ＆ドロップし、「アップロード」を押します。選択したファイル名と件数を確認できます。すべてのファイルを検証し、不正なファイルや同名の重複があれば、どのファイルも保存せずファイル名付きのエラーを表示します。ファイル名は現在のプログラムコードと完全一致する `FRP001.pdf` のような名前にしてください（拡張子は小文字の `.pdf`）。50MB以下で、PDFヘッダーのあるファイルを受け付けます。選択した年会内の演題を照合し、アップロード済みならStatusに緑丸とダウンロードリンクを表示します。同じ演題への再アップロードは差し替えになります。未採番の演題は先にプログラム番号を設定してください。

環境変数 `PROCEEDINGS_ROOT` で保存先を指定します。例えば起動環境に `PROCEEDINGS_ROOT=/data/proceedings` を設定すると、`/data/proceedings/2027/FRP001.pdf` に保存します。指定先にはアプリの実行ユーザーの書き込み権限が必要です。未指定の場合は `media/2027/FRP001.pdf` になります。同名の再アップロードは同じパスのファイルを差し替えます。ダウンロードURLも `/procgen/2027/FRP001/pdf/` のようにプログラムコードを使います。

アップロード後、同じ画面の「ヘッダー・フッター付きPDFの生成」で巻名、ヘッダー2行、開始ページ番号を入力し、「加工済みPDFを生成・公開」を押します。生成には演題の閲覧・変更権限が必要です。2025・2026年は元ビルダーの設定を初期表示します。それ以外の年はヘッダーを入力してください。入力値は生成ごとの指定で、データベースには保存しません。

`pasj_proceedings_builder/pdf-processing` のPDF加工処理を `program/proceedings_pdf.py` に取り込んでいます。青字の2行ヘッダー、巻名と講演番号（奇数ページは右、偶数ページは左）、中央の通しページ番号、英語の題目・著者メタデータ、PDFページラベルを付与します。元仕様と同じ595×791ptに用紙サイズを変更するため、原稿の端が切れる場合があります。生成したPDFを確認してから公開してください。欧文フォントを使うため、画面の文言は半角英数字・記号で指定します。

対象は選択した年会の採番・セッション割り当て済みの演題で、`program.xlsx` / JSONと同じセッション・演題順に通しページを振ります。取り消し演題もPDFがあれば含めます。未アップロード演題は一覧に残して開始ページを空欄／`null` とし、ページを消費しません。未割り当て・未採番の演題は対象外です。破損・パスワード付きPDFなどで加工に失敗した場合は演題コード付きのエラーを表示し、前回の公開内容を維持します。

元PDFは変更せず、加工結果はサーバーに保存・公開します。「結合PDFをダウンロード」は別ボタンで、最後に公開した個別PDFを `proceedings_list.json` のプログラム順に結合し、`proceedings-<年>.pdf` として取得します。未アップロード演題はスキップし、印刷済みの通しページ番号とPDFページラベルを保持します。ZIPではなく1つのPDFを返し、ヘッダー・フッターの再生成は行いません。未生成の場合はダウンロードボタンが無効になります。取得にはログインと演題の閲覧権限が必要です。再アップロード・編成変更・再採番後は再生成してください。個別の公開PDFとサーバー上のページ一覧は引き続き保持し、結合PDFはダウンロード時だけ作成します。既存のアップロード済みリンクからは元PDFを取得できます。

加工済みPDFの公開URLは `http://localhost:8000/2026/web_publish/FROA001.pdf` の形式です。ログイン不要でブラウザにPDFを表示します。生成後に演題一覧に「公開PDF」リンクが現れます。この公開はタイムテーブルの公開設定とは独立しており、生成ボタンを押すと公開まで実行します。

保存先は環境変数 `PROCEEDINGS_PUBLISH_ROOT` で指定します（元PDFの `PROCEEDINGS_ROOT` とは別です）。例えば `PROCEEDINGS_PUBLISH_ROOT=/data/published_proceedings` なら `/data/published_proceedings/2026/web_publish/FROA001.pdf` で参照できます。未指定時はプロジェクト内の `published_proceedings/` 以下です。設定変更後はDjangoを再起動してください。既存の生成物は自動移動しないため、新しい保存先では再生成してください。保存先にはアプリの実行ユーザーの書き込み権限とシンボリックリンクを作成できるファイルシステムが必要です。

全件の生成・保存が成功した場合だけ、年会ごとの `web_publish` シンボリックリンクを新しい生成ディレクトリ（同じ年ディレクトリ内の `.proceedings-*`）に一括で切り替えます。失敗時は前回の公開内容を維持します。再生成で対象から外れた古い講演番号のPDFは公開URLから取得できなくなります。再アップロードや編成変更だけでは公開PDFは変わらず、再生成まで前回の内容を配信します。ページ一覧2ファイルも同じディレクトリに保存しますが、公開URLで配信するのはPDFのみです。

以前の生成ディレクトリは配信中のアクセスを妨げないよう保持します。容量管理が必要な場合は、生成処理とPDF配信が動いていない保守時間に、`web_publish` のリンク先以外の `.proceedings-*` ディレクトリを削除できます。`web_publish` を通常のディレクトリとして手動作成しないでください。URLはDjangoが配信するため、開発サーバーでも利用でき、本番でもこのURLをDjangoへ転送すれば利用できます。

依存ライブラリは `.venv/bin/python -m pip install -r requirements.txt` で導入します（PyMuPDFを追加）。標準ではPDF組み込みのTimesを使います。Times New Romanを使う場合は、`times.ttf`、`timesi.ttf`、`timesbd.ttf` を置いたディレクトリを環境変数 `PROCEEDINGS_FONT_DIR` に指定します。生成は同期処理のため、大量のPDFではWebサーバーのリクエストタイムアウトを運用環境に合わせて調整してください。


再採番してもDBに記録したPDFとの対応は維持しますが、既存ファイルは自動改名しません。再アップロードすると現在のコードのパスに保存します。再採番前の別演題のPDFと保存先が衝突する場合は、上書きせずエラーにします。旧方式でアップロード済みのファイルも自動移動しません。保存先を変更する場合は、旧保存ルート（初期設定では `media/`）の内容を相対パスを維持して新ルートにコピーしてください。再アップロード時に新形式のパスへ切り替わります。

バックアップにはDBと保存先の両方を含めてください。PDFは権限確認付きのビューから配信するため、本番環境でもこの保存先を直接公開しないでください。

## タイムテーブル

編成画面の「タイムテーブル公開」スイッチで、年会ごとに公開・非公開を切り替えます。切り替えには編成画面の閲覧権限と「年会情報の変更」権限が必要です。非公開の年会は公開一覧に表示されず、`/<年>/` と旧URLの `/timetable/<年>/` には「プログラムが確定するまでお待ちください」という案内を表示します。演題やタイムテーブルの内容は表示しません。編成画面では非公開でも確認・編集できます。新規年会は非公開で作成され、この機能導入前からある年会は公開状態を維持します。

編成画面の `/organize/<年>/` では「セッション編成」と「タイムテーブル」のタブを切り替えられます。タイムテーブルのセッション移動は変更権限のあるログインユーザーに限られます。公開ページの `/<年>/` は同じ時間割を閲覧でき、ドラッグ操作はできません。日付を横並びにし、各日で部屋ごとの時間割を表示します。横幅に収まらない場合は横スクロールできます。セッションの開始・終了時刻、名称、コード、プログラム番号の範囲を確認でき、時間枠を選ぶと下の演題一覧が開きます。演題ごとの時刻が未入力なら、セッション開始時刻と1講演あたりの時間から表示時刻を計算します。会期内のセッション情報を更新すると、ページの再読み込みでタイムテーブルにも反映されます。

施設報告ポスターの演題は、対応する2つのポスター時間枠にそれぞれ表示されます。

セッションの変更権限があるユーザーは、編成画面のタイムテーブルタブでセッションカードを別の日・部屋の列へドラッグして日付、部屋、開始時刻を変更できます。開始時刻は5分刻みです。セッションの長さは維持され、終了時刻と個別に設定済みの演題時刻も同じ分だけ移動します。会期外の日付には移動できません。

休憩や式典など演題のない枠は、セッション作成時に任意の「講演なしの枠の長さ（分）」を設定すると終了時刻まで表示できます。日付や開始時刻が未設定のセッションは、タイムテーブル下部にまとめて表示します。

管理画面の「演題」にある著者の入力欄と、折りたたまれた「元データの著者表記」は別々に保存されます。著者の名前や所属を編集しても、`<sup>` などのタグを含む元データの文字列は自動更新されません。元データの文字列を変える場合は、その欄を直接編集してください。

再インポートでは演題登録番号で同一演題を判定し、Excel由来の演題・著者情報を更新します。管理画面で修正した著者欄と元データ欄も、再インポート時にExcelの内容で上書きされます。編成情報、状態、メモは保持します。Excelに存在しなくなった演題は削除しません。

本番運用時は `PROGRAM_SECRET_KEY`、`PROGRAM_DEBUG=0`、`PROGRAM_ALLOWED_HOSTS` を設定してください。Excelには個人情報が含まれるため、管理画面のアカウントとファイルの保管に注意してください。

セッション編成画面では、セッション情報の横の鉛筆アイコンからポップアップで編集できます。口頭発表では同じポップアップ内でカテゴリーごとの座長も編集し、まとめて保存できます。セッションの変更権限が必要です。

## ログイン・ログアウト・パスワード再設定

トップページの「ログイン」から `/login/` に進みます。編成画面とプロシーディングス画面（年会一覧を含む）のヘッダーにはユーザー名と「ログアウト」ボタンを表示します。ログアウト後はトップページに戻ります。

パスワードを忘れた場合は、ログイン画面の「パスワードを忘れた方はこちら」から登録メールアドレスを入力します。メール内のリンクから新しいパスワードを設定し、再度ログインしてください。リンクは1時間有効で、変更後は再利用できません。事前に管理画面の「ユーザー」で各利用者のメールアドレスを登録してください。未登録のアドレスや無効なアカウントには送信せず、画面上は同じ案内を表示します。

開発時（`PROGRAM_DEBUG=1`）の初期設定ではメールを実送信せず、`runserver` のターミナルに本文と再設定URLを出力します。実際にメールを送る場合は、起動前にSMTP設定を環境変数として設定してください。

```bash
export PROGRAM_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
export PROGRAM_EMAIL_HOST=smtp.example.com
export PROGRAM_EMAIL_PORT=587
export PROGRAM_EMAIL_HOST_USER=your-smtp-user
export PROGRAM_EMAIL_HOST_PASSWORD='your-smtp-password'
export PROGRAM_EMAIL_USE_TLS=1
export PROGRAM_EMAIL_USE_SSL=0
export PROGRAM_DEFAULT_FROM_EMAIL='プログラム編成システム <noreply@example.com>'
```

SMTPサービスから指定された値に置き換えてください。SSL接続（通常465番ポート）を使用する場合は `PROGRAM_EMAIL_USE_TLS=0` と `PROGRAM_EMAIL_USE_SSL=1` にします。`.env` ファイルの自動読み込みはありません。デプロイ環境の環境変数設定等を使用してください。

本番環境では `PROGRAM_DEBUG=0`、固有の `PROGRAM_SECRET_KEY`、公開ホスト名を列挙した `PROGRAM_ALLOWED_HOSTS` とSMTP設定を指定します。再設定URLはアクセスしたホスト名・HTTP/HTTPSから生成するため、利用者がアクセスできる公開HTTPS URLから申請してください。リバースプロキシを使用する場合は、Djangoが元のHTTPS接続を正しく判定できるようにプロキシ構成に合わせて設定してください。
