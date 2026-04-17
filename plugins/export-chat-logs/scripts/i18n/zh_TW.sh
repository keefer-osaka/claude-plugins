# 繁體中文 locale strings for shell scripts (upload.sh, save-config.sh)

# upload.sh - error / warning
ERR_NOT_CONFIGURED="❌ 尚未設定，請執行：/export-chat-logs:setup"
ERR_TOKEN_EMPTY="❌ Telegram Bot Token 為空，請執行：/export-chat-logs:setup"
ERR_CHATID_EMPTY="❌ Telegram chat_id 為空，請執行：/export-chat-logs:setup"
WARN_NO_SESSIONS="⚠️  過去 %DAYS% 天內未找到任何對話，跳過。"

# upload.sh - summary text (Telegram message)
SUMMARY_HEADER="📦 對話紀錄匯出"
SUMMARY_USER="👤 使用者：%GIT_USER%"
SUMMARY_PERIOD="📅 期間：%START_DATE% ~ %TODAY%（最近 %DAYS% 天）"
SUMMARY_STATS="📊 統計：%CC_SESSIONS% 個對話"
SUMMARY_SIZE="💾 檔案大小：%ZIP_SIZE%"
SUMMARY_FORMAT_HTML="📝 格式：HTML（語法高亮 + 互動式圖表）"
SUMMARY_FORMAT_MD="📝 格式：Markdown（已省略工具呼叫與技術細節）"
MSG_DONE="✅ 完成！Claude Code：%CC_SESSIONS% 個對話，壓縮檔：%ZIP_SIZE%，已傳送至 Telegram"
STATS_REPORT_SLUG="claude-code_使用報告"
STATS_REPORT_SLUG_COWORK="claude-cowork_使用報告"

# Cowork
SUMMARY_STATS_COWORK="📊 統計：%CC_SESSIONS% 個對話（Claude Code）+ %CW_SESSIONS% 個對話（Claude Cowork）"
MSG_DONE_COWORK="✅ 完成！Claude Code：%CC_SESSIONS% 個對話，Claude Cowork：%CW_SESSIONS% 個對話，壓縮檔：%ZIP_SIZE%，已傳送至 Telegram"

# save-config.sh
ERR_TOKEN_REQUIRED="❌ 需要提供 Token：bash save-config.sh <token> <chat_id> [timezone] [lang] [format] [cowork]"
ERR_CHATID_REQUIRED="❌ 需要提供 Chat ID：bash save-config.sh <token> <chat_id> [timezone] [lang] [format] [cowork]"
MSG_CONFIG_SAVED="✅ 設定已儲存（Token + Chat ID + 時區 %TZ_LABEL% + 語言 %LANG% + 格式 %FORMAT% + Cowork %COWORK%）"

# install-launchd.sh - weekday names (launchd: 0/7=Sunday, 1=Monday, ..., 6=Saturday)
LAUNCHD_DAY_0="日"
LAUNCHD_DAY_1="一"
LAUNCHD_DAY_2="二"
LAUNCHD_DAY_3="三"
LAUNCHD_DAY_4="四"
LAUNCHD_DAY_5="五"
LAUNCHD_DAY_6="六"
LAUNCHD_DAY_7="日"

# install-launchd.sh - terminal success message
MSG_LAUNCHD_INSTALLED="✅ launchd agent 已安裝並載入。"
MSG_LAUNCHD_SCHEDULE="排程：每週%DAY_NAME% %HH_MM%（本地時間）"
MSG_LAUNCHD_PLIST="Plist：%PLIST_FILE%"
MSG_LAUNCHD_LOG="Log：  %LOG_FILE%"
MSG_LAUNCHD_TEST="立即測試執行："
MSG_LAUNCHD_REMOVE="移除："
MSG_LAUNCHD_SUMMARY_SAVED="摘要已儲存：%SUMMARY_FILE%"

# install-launchd.sh - markdown summary file
LAUNCHD_MD_TITLE="# export-chat-logs 自動匯出"
LAUNCHD_MD_SCHEDULE="排程"
LAUNCHD_MD_SCHEDULE_VAL="每週%DAY_NAME% %HH_MM%（本地時間）"
LAUNCHD_MD_LOG="Log"
LAUNCHD_MD_COMMANDS="## 指令"
LAUNCHD_MD_TEST="立即測試執行："
LAUNCHD_MD_REMOVE="移除："
