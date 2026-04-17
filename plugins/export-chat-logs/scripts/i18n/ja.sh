# 日本語 locale strings for shell scripts (upload.sh, save-config.sh)

# upload.sh - error / warning
ERR_NOT_CONFIGURED="❌ 未設定です。実行してください：/export-chat-logs:setup"
ERR_TOKEN_EMPTY="❌ Telegram Bot Token が空です。実行してください：/export-chat-logs:setup"
ERR_CHATID_EMPTY="❌ Telegram chat_id が空です。実行してください：/export-chat-logs:setup"
WARN_NO_SESSIONS="⚠️  過去 %DAYS% 日間にセッションが見つかりませんでした。スキップします。"

# upload.sh - summary text (Telegram message)
SUMMARY_HEADER="📦 チャットログエクスポート"
SUMMARY_USER="👤 ユーザー：%GIT_USER%"
SUMMARY_PERIOD="📅 期間：%START_DATE% ~ %TODAY%（過去 %DAYS% 日間）"
SUMMARY_STATS="📊 統計：%CC_SESSIONS% セッション"
SUMMARY_SIZE="💾 ファイルサイズ：%ZIP_SIZE%"
SUMMARY_FORMAT_HTML="📝 形式：HTML（シンタックスハイライト + インタラクティブグラフ）"
SUMMARY_FORMAT_MD="📝 形式：Markdown（ツール呼び出しと技術的詳細は省略）"
MSG_DONE="✅ 完了！Claude Code：%CC_SESSIONS% セッション、zip：%ZIP_SIZE%、Telegram に送信済み"
STATS_REPORT_SLUG="claude-code_使用レポート"
STATS_REPORT_SLUG_COWORK="claude-cowork_使用レポート"

# Cowork
SUMMARY_STATS_COWORK="📊 統計：%CC_SESSIONS% セッション（Claude Code）+ %CW_SESSIONS% セッション（Claude Cowork）"
MSG_DONE_COWORK="✅ 完了！Claude Code：%CC_SESSIONS% セッション、Claude Cowork：%CW_SESSIONS% セッション、zip：%ZIP_SIZE%、Telegram に送信済み"

# save-config.sh
ERR_TOKEN_REQUIRED="❌ Token が必要です：bash save-config.sh <token> <chat_id> [timezone] [lang] [format] [cowork]"
ERR_CHATID_REQUIRED="❌ Chat ID が必要です：bash save-config.sh <token> <chat_id> [timezone] [lang] [format] [cowork]"
MSG_CONFIG_SAVED="✅ 設定を保存しました（Token + Chat ID + タイムゾーン %TZ_LABEL% + 言語 %LANG% + 形式 %FORMAT% + Cowork %COWORK%）"

# install-launchd.sh - weekday names (launchd: 0/7=Sunday, 1=Monday, ..., 6=Saturday)
LAUNCHD_DAY_0="日曜日"
LAUNCHD_DAY_1="月曜日"
LAUNCHD_DAY_2="火曜日"
LAUNCHD_DAY_3="水曜日"
LAUNCHD_DAY_4="木曜日"
LAUNCHD_DAY_5="金曜日"
LAUNCHD_DAY_6="土曜日"
LAUNCHD_DAY_7="日曜日"

# install-launchd.sh - terminal success message
MSG_LAUNCHD_INSTALLED="✅ launchd エージェントをインストールして読み込みました。"
MSG_LAUNCHD_SCHEDULE="スケジュール：毎週%DAY_NAME% %HH_MM%（ローカル時間）"
MSG_LAUNCHD_PLIST="Plist：%PLIST_FILE%"
MSG_LAUNCHD_LOG="ログ：  %LOG_FILE%"
MSG_LAUNCHD_TEST="すぐにテスト実行："
MSG_LAUNCHD_REMOVE="削除するには："
MSG_LAUNCHD_SUMMARY_SAVED="サマリー保存先：%SUMMARY_FILE%"

# install-launchd.sh - markdown summary file
LAUNCHD_MD_TITLE="# export-chat-logs 自動エクスポート"
LAUNCHD_MD_SCHEDULE="スケジュール"
LAUNCHD_MD_SCHEDULE_VAL="毎週%DAY_NAME% %HH_MM%（ローカル時間）"
LAUNCHD_MD_LOG="ログ"
LAUNCHD_MD_COMMANDS="## コマンド"
LAUNCHD_MD_TEST="すぐにテスト実行："
LAUNCHD_MD_REMOVE="削除するには："
