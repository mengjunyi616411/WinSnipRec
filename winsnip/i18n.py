"""Interface translations.

Keys are the Simplified Chinese source strings that appear in the code, so an
untranslated string degrades to Chinese instead of showing a placeholder. The
table is written as source: (繁體中文, English, 日本語) so a missing column is
obvious at a glance.

Usage:
    from .i18n import t
    label = QLabel(t("新建"))
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Order matters: it is the order of the dropdown.
LANGUAGES: list[tuple[str, str]] = [
    ("system", "跟随系统"),
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
]

# Everything that is not Simplified Chinese needs a right-hand column.
TRANSLATED = ("zh-Hant", "en", "ja")

TABLE: dict[str, tuple[str, str, str]] = {
    # source (zh-Hans)                 繁體中文                    English                        日本語
    "秒": ("秒", "s", "秒"),
    "秒后开始": ("秒後開始", "s to start", "秒後に開始"),
    "不采集": ("不擷取", "Off", "使用しない"),
    "中": ("中", "Medium", "中"),
    "低": ("低", "Low", "低"),
    "高": ("高", "High", "高"),
    "自动": ("自動", "Auto", "自動"),
    "浅色": ("淺色", "Light", "ライト"),
    "深色": ("深色", "Dark", "ダーク"),
    "跟随系统": ("跟隨系統", "Follow system", "システムに従う"),
    "开启": ("開啟", "On", "オン"),
    "采集": ("擷取", "Capture", "キャプチャ"),
    "视频": ("視訊", "Video", "ビデオ"),
    "音频": ("音訊", "Audio", "オーディオ"),
    "图片": ("圖片", "Image", "画像"),
    "截图": ("截圖", "Screenshot", "スクリーンショット"),
    "录屏": ("錄影", "Recording", "録画"),
    "录制": ("錄製", "Record", "録画"),
    "混音": ("混音", "Mix", "ミックス"),
    "监视器": ("監視器", "Monitor", "モニター"),
    "立体声混音": ("立體聲混音", "Stereo Mix", "ステレオ ミキサー"),
    "设置": ("設定", "Settings", "設定"),
    "关于": ("關於", "About", "情報"),
    "退出": ("結束", "Exit", "終了"),
    "关闭": ("關閉", "Close", "閉じる"),
    "保存": ("儲存", "Save", "保存"),
    "复制": ("複製", "Copy", "コピー"),
    "确定": ("確定", "OK", "OK"),
    "取消 (Esc)": ("取消 (Esc)", "Cancel (Esc)", "キャンセル (Esc)"),
    "完成": ("完成", "Done", "完了"),
    "新建": ("新增", "New", "新規"),
    "新建截图": ("新增截圖", "New screenshot", "新規スクリーンショット"),
    "新建录屏": ("新增錄影", "New recording", "新規録画"),
    "截图失败": ("截圖失敗", "Screenshot failed", "スクリーンショットに失敗"),
    "操作失败": ("操作失敗", "Action failed", "操作に失敗"),
    "保存失败": ("儲存失敗", "Save failed", "保存に失敗"),
    "已保存": ("已儲存", "Saved", "保存しました"),
    "另存为": ("另存新檔", "Save as", "名前を付けて保存"),
    "在文件夹中显示": ("在資料夾中顯示", "Show in folder", "フォルダーに表示"),
    "已复制到剪贴板": ("已複製到剪貼簿", "Copied to clipboard", "クリップボードにコピーしました"),
    "打开保存文件夹": ("開啟儲存資料夾", "Open save folder", "保存フォルダーを開く"),
    "无法打开文件夹": ("無法開啟資料夾", "Cannot open the folder", "フォルダーを開けません"),
    "选择文件夹": ("選擇資料夾", "Choose folder", "フォルダーを選択"),
    "更改…": ("變更…", "Change…", "変更…"),
    "框架": ("框架", "Frame", "フレーム"),
    "版本 ": ("版本 ", "Version ", "バージョン "),
    "截图工具": ("截圖工具", "Snipping Tool", "切り取りツール"),
    "截图工具 WinSnipRec": ("截圖工具 WinSnipRec", "Snipping Tool WinSnipRec",
                            "切り取りツール WinSnipRec"),
    "截图工具 — ": ("截圖工具 — ", "Snipping Tool — ", "切り取りツール — "),
    "截图工具仍在运行": ("截圖工具仍在執行", "WinSnipRec is still running",
                          "WinSnipRec は実行中です"),
    "屏幕截图": ("螢幕擷取", "Screen capture", "画面キャプチャ"),
    "屏幕录制 ": ("螢幕錄影 ", "Screen recording ", "画面録画 "),
    "截图 ": ("截圖 ", "Screenshot ", "スクリーンショット "),
    "视频文件夹": ("視訊資料夾", "Video folder", "ビデオ フォルダー"),
    "图片文件夹": ("圖片資料夾", "Image folder", "画像フォルダー"),
    "保存位置": ("儲存位置", "Save location", "保存先"),
    "保存位置已更新": ("儲存位置已更新", "Save location updated", "保存先を更新しました"),
    "主题": ("主題", "Theme", "テーマ"),
    "外观": ("外觀", "Appearance", "外観"),
    "浅色或深色外观，默认跟随 Windows 设置":
        ("淺色或深色外觀，預設跟隨 Windows 設定",
         "Light or dark appearance; follows Windows by default",
         "ライトまたはダーク。既定では Windows に従います"),
    "界面风格": ("介面風格", "Interface style", "インターフェイス スタイル"),
    "窗口圆角、材质与标题栏按钮的样式":
        ("視窗圓角、材質與標題列按鈕的樣式",
         "Window corners, material and caption buttons",
         "ウィンドウの角、素材、タイトル バーのボタンのスタイル"),
    "界面风格已切换": ("介面風格已切換", "Interface style changed", "スタイルを変更しました"),
    "背景材质": ("背景材質", "Backdrop material", "背景の素材"),
    "经典（壁纸）": ("經典（壁紙）", "Classic (wallpaper)", "クラシック（壁紙）"),
    "强制实时": ("強制即時", "Force real-time", "リアルタイムを強制"),
    "本机实测不支持系统实时模糊（已自动回退到壁纸材质）":
        ("本機實測不支援系統即時模糊（已自動退回壁紙材質）",
         "This PC does not render system backdrop blur; using the wallpaper material",
         "この PC ではシステムの背景ぼかしが描画されないため、壁紙素材を使用します"),
    "本机支持实时模糊，用它更真实；不支持时会自动回退":
        ("本機支援即時模糊，使用它更真實；不支援時會自動退回",
         "This PC supports real-time blur; it falls back automatically when it does not",
         "この PC はリアルタイムぼかしに対応しています。非対応の場合は自動で切り替わります"),
    "光效强度": ("光效強度", "Pointer light strength", "ポインター ライトの強さ"),
    "Windows 10 风格下跟随鼠标的高光强度，也用于按钮悬停边框":
        ("Windows 10 風格下跟隨滑鼠的高光強度，也用於按鈕暫留邊框",
         "Strength of the Windows 10 pointer light; also the button hover border",
         "Windows 10 スタイルでマウスを追う光の強さ。ボタンのホバー枠にも使われます"),
    "界面动画": ("介面動畫", "Interface animations", "インターフェイスのアニメーション"),
    "启动动画、窗口淡入与滑动效果；Windows 关闭「显示动画」时自动跳过":
        ("啟動動畫、視窗淡入與滑動效果；Windows 關閉「顯示動畫」時自動略過",
         "Splash, window fade and slide; skipped when Windows disables animations",
         "起動アニメーション、フェードとスライド。Windows でアニメーションが無効なら省略"),
    "界面动画已开启": ("介面動畫已開啟", "Interface animations on",
                        "インターフェイスのアニメーションを有効にしました"),
    "界面动画已关闭": ("介面動畫已關閉", "Interface animations off",
                        "インターフェイスのアニメーションを無効にしました"),
    "启动动画、窗口淡入与滑动效果已启用":
        ("啟動動畫、視窗淡入與滑動效果已啟用",
         "Splash, window fade and slide are on", "起動アニメーションとフェードを有効にしました"),
    "界面将立即切换，不再有过渡效果":
        ("介面將立即切換，不再有過渡效果",
         "The interface switches instantly, with no transition",
         "画面はトランジションなしで即座に切り替わります"),
    "最小化到系统托盘": ("最小化到系統匣", "Minimize to the notification area",
                          "通知領域に最小化"),
    "关闭窗口时继续在后台运行，可随时用快捷键唤起":
        ("關閉視窗時繼續在背景執行，可隨時用快速鍵喚起",
         "Keeps running in the background; bring it back with a hotkey",
         "閉じてもバックグラウンドで動作し、ホットキーで呼び出せます"),
    "录制完成后打开文件夹": ("錄製完成後開啟資料夾", "Open the folder when finished",
                              "録画完了後にフォルダーを開く"),
    "结束时自动在资源管理器中定位文件":
        ("結束時自動在檔案總管中定位檔案",
         "Selects the file in Explorer when the recording ends",
         "終了時にエクスプローラーでファイルを選択します"),
    "开机自动启动": ("開機自動啟動", "Start with Windows", "Windows 起動時に開始"),
    "关闭时登录 Windows 不会自动运行": ("關閉時登入 Windows 不會自動執行",
                                          "Off: nothing runs when you sign in",
                                          "オフ: サインイン時に実行されません"),
    "登录 Windows 后将在通知区域静默运行":
        ("登入 Windows 後將在通知區域靜默執行",
         "Runs quietly in the notification area after you sign in",
         "サインイン後は通知領域で静かに動作します"),
    "登录 Windows 后会在通知区域静默运行，可直接用快捷键唤起":
        ("登入 Windows 後會在通知區域靜默執行，可直接用快速鍵喚起",
         "Runs quietly in the notification area after sign-in; call it up with a hotkey",
         "サインイン後は通知領域で静かに対応し、ホットキーで呼び出せます"),
    "已从注册表启动项中移除": ("已從登錄啟動項中移除", "Removed from the startup entries",
                                "スタートアップから削除しました"),
    "已开启：登录后静默运行在通知区域 · {0}":
        ("已開啟：登入後靜默執行於通知區域 · {0}",
         "On: runs quietly in the notification area · {0}",
         "オン: 通知領域で静かに動作 · {0}"),
    "已开启（指向另一份程序）：{0}": ("已開啟（指向另一份程式）：{0}",
                                        "On (points at another copy): {0}",
                                        "オン（別のコピーを指しています）: {0}"),
    "已开启，但指向的程序已不存在：{0}": ("已開啟，但指向的程式已不存在：{0}",
                                            "On, but the target no longer exists: {0}",
                                            "オンですが、対象が存在しません: {0}"),
    "原本就没有开启": ("原本就沒有開啟", "It was not enabled to begin with",
                        "もともと有効ではありません"),
    "开机自动启动已": ("開機自動啟動已", "Start with Windows ", "Windows 起動時の開始: "),
    "开机自动启动已开启": ("開機自動啟動已開啟", "Start with Windows is on",
                            "Windows 起動時の開始を有効にしました"),
    "开机自动启动已关闭": ("開機自動啟動已關閉", "Start with Windows is off",
                            "Windows 起動時の開始を無効にしました"),
    "开机自启设置失败": ("開機自啟設定失敗", "Could not change the startup setting",
                          "スタートアップ設定を変更できませんでした"),
    "写入注册表失败：{0}": ("寫入登錄失敗：{0}", "Could not write the registry entry: {0}",
                            "レジストリに書き込めません: {0}"),
    "删除注册表项失败：{0}": ("刪除登錄項目失敗：{0}",
                              "Could not delete the registry entry: {0}",
                              "レジストリ エントリを削除できません: {0}"),
    "帧率": ("影格速率", "Frame rate", "フレーム レート"),
    "帧率越高越流畅，文件也越大": ("影格速率越高越流暢，檔案也越大",
                                    "Higher frame rates look smoother and produce larger files",
                                    "フレーム レートが高いほど滑らかですが、ファイルは大きくなります"),
    "画质": ("畫質", "Quality", "画質"),
    "H.264 编码质量 (CRF)": ("H.264 編碼品質 (CRF)", "H.264 quality (CRF)", "H.264 画質 (CRF)"),
    "高质量 (CRF 18)": ("高品質 (CRF 18)", "High (CRF 18)", "高画質 (CRF 18)"),
    "较高 (CRF 20)": ("較高 (CRF 20)", "Higher (CRF 20)", "やや高 (CRF 20)"),
    "标准 (CRF 23)": ("標準 (CRF 23)", "Standard (CRF 23)", "標準 (CRF 23)"),
    "较小体积 (CRF 26)": ("較小體積 (CRF 26)", "Smaller (CRF 26)", "小さめ (CRF 26)"),
    "开始前倒计时": ("開始前倒數", "Countdown before starting", "開始前のカウントダウン"),
    "开始前延迟": ("開始前延遲", "Delay before starting", "開始前の遅延"),
    "点击新建后等待指定秒数再开始":
        ("點擊新增後等待指定秒數再開始",
         "Waits the given number of seconds after you press New",
         "「新規」を押してから指定した秒数だけ待ちます"),
    "无延迟": ("無延遲", "No delay", "遅延なし"),
    "延迟已设置": ("延遲已設定", "Delay updated", "遅延を設定しました"),
    "录制声音": ("錄製聲音", "Sound", "音声"),
    "录制系统声音": ("錄製系統聲音", "Record system audio", "システム音声を録音"),
    "录制麦克风": ("錄製麥克風", "Record microphone", "マイクを録音"),
    "麦克风声音": ("麥克風聲音", "Microphone", "マイク"),
    "麦克风": ("麥克風", "Microphone", "マイク"),
    "麦克风设备": ("麥克風裝置", "Microphone device", "マイク デバイス"),
    "麦克风已": ("麥克風已", "Microphone ", "マイク: "),
    "麦克风已开启": ("麥克風已開啟", "Microphone on", "マイクをオンにしました"),
    "麦克风已关闭": ("麥克風已關閉", "Microphone off", "マイクをオフにしました"),
    "系统声音已": ("系統聲音已", "System audio ", "システム音声: "),
    "系统声音已开启": ("系統聲音已開啟", "System audio on", "システム音声をオンにしました"),
    "系统声音已关闭": ("系統聲音已關閉", "System audio off", "システム音声をオフにしました"),
    "系统声音设备": ("系統聲音裝置", "System audio device", "システム音声デバイス"),
    "系统声音设备（回环）": ("系統聲音裝置（回環）", "System audio device (loopback)",
                              "システム音声デバイス（ループバック）"),
    "音频设备": ("音訊裝置", "Audio devices", "オーディオ デバイス"),
    "未找到音频设备": ("未找到音訊裝置", "No audio devices found", "オーディオ デバイスが見つかりません"),
    "未找到麦克风": ("未找到麥克風", "No microphone found", "マイクが見つかりません"),
    "正在检测音频设备…": ("正在偵測音訊裝置…", "Detecting audio devices…",
                            "オーディオ デバイスを検出しています…"),
    "（未选择）": ("（未選擇）", "(None)", "（未選択）"),
    # 带占位符的模板：语序在不同语言里不一样，不能靠拼接
    "{0} 秒": ("{0} 秒", "{0} s", "{0} 秒"),
    "{0} 秒后开始": ("{0} 秒後開始", "Starts in {0} s", "{0} 秒後に開始"),
    "按 {0} 开始截图": ("按 {0} 開始截圖", "Press {0} to take a screenshot",
                        "{0} でスクリーンショット"),
    "按 {0} 开始录屏": ("按 {0} 開始錄影", "Press {0} to start recording", "{0} で録画を開始"),
    "{0}将保存到 {1}": ("{0}將儲存到 {1}", "{0} will be saved to {1}", "{0} は {1} に保存されます"),
    "同时保存到 {0}": ("同時儲存到 {0}", "Also saved to {0}", "{0} にも保存しました"),
    "截图工具 — {0}": ("截圖工具 — {0}", "Snipping Tool — {0}", "切り取りツール — {0}"),
    "当前：{0}": ("目前：{0}", "Current: {0}", "現在: {0}"),
    "版本 {0}": ("版本 {0}", "Version {0}", "バージョン {0}"),
    "制作人：天童 アリス": ("製作人：天童 アリス", "Producer: 天童 アリス",
                            "制作：天童 アリス"),
    "搜索设置": ("搜尋設定", "Search settings", "設定を検索"),
    "没有匹配的设置项": ("沒有符合的設定項", "No matching settings",
                          "一致する設定がありません"),
    # 彩蛋
    "彩蛋": ("彩蛋", "Easter egg", "イースターエッグ"),
    "你是萝莉控吗？": ("你是蘿莉控嗎？", "Are you a lolicon?", "ロリコンですか？"),
    "是": ("是", "Yes", "はい"),
    "否": ("否", "No", "いいえ"),
    "再选一次？": ("再選一次？", "Choose again?", "もう一度選んでください？"),
    "……否": ("……否", "…No", "…いいえ"),
    "彩蛋图片缺失": ("彩蛋圖片缺失", "Easter-egg image missing", "画像が見つかりません"),
    "界面语言": ("介面語言", "Interface language", "表示言語"),
    "首次使用引导": ("首次使用引導", "First-run guide", "初回ガイド"),
    "重新运行引导": ("重新執行引導", "Run the guide again", "ガイドをもう一度"),
    "欢迎": ("歡迎", "Welcome", "ようこそ"),
    "跳过": ("略過", "Skip", "スキップ"),
    "上一步": ("上一步", "Back", "戻る"),
    "下一步": ("下一步", "Next", "次へ"),
    "第 {0} / {1} 步": ("第 {0} / {1} 步", "Step {0} of {1}", "ステップ {0} / {1}"),
    "让截图工具变成你喜欢的样子":
        ("讓截圖工具變成你喜歡的樣子",
         "Make WinSnipRec look the way you like",
         "切り取りツールをお好みの見た目に"),
    "接下来几个问题，帮你把外观调成自己喜欢的样子。每一步都会立刻作用在这个窗口上，你能直接看到效果。":
        ("接下來幾個問題，幫你把外觀調成自己喜歡的樣子。"
         "每一步都會立刻作用在這個視窗上，你能直接看到效果。",
         "A few quick questions to set the appearance the way you like it. "
         "Every choice applies to this very window, so you see it right away.",
         "いくつかの質問で、見た目をお好みに合わせます。"
         "選んだ内容はこのウィンドウにすぐ反映されるので、その場で確認できます。"),
    "这些选项随时可以在设置里修改":
        ("這些選項隨時可以在設定裡修改",
         "You can change all of this later in Settings",
         "これらの設定は後から設定で変更できます"),
    "选一个你更习惯的外观。选中的那一刻，这个窗口就会变成那个样子——圆角、材质和标题栏按钮都会跟着变。":
        ("選一個你更習慣的外觀。選中的那一刻，這個視窗就會變成那個樣子——"
         "圓角、材質與標題列按鈕都會跟著變。",
         "Pick the look you are used to. The moment you choose, this window becomes it - "
         "corners, material and caption buttons all change.",
         "使い慣れた見た目を選んでください。選んだ瞬間にこのウィンドウがその外観になり、"
         "角の丸み、素材、タイトル バーのボタンも変わります。"),
    "浅色或深色。选「跟随系统」就跟着 Windows 的设置走，系统切成深色时这个窗口也会变。":
        ("淺色或深色。選「跟隨系統」就跟著 Windows 的設定走，系統切成深色時這個視窗也會變。",
         "Light or dark. “Follow system” tracks Windows, so this window turns dark "
         "when Windows does.",
         "ライトまたはダーク。「システムに従う」を選ぶと Windows の設定に追従し、"
         "システムがダークになればこのウィンドウも変わります。"),
    "Windows 10 风格下，鼠标移动会带起一束光。把鼠标移到这个窗口上划一划，就能感受到当前档位的强弱。":
        ("Windows 10 風格下，滑鼠移動會帶起一束光。"
         "把滑鼠移到這個視窗上划一划，就能感受到目前檔位的強弱。",
         "In the Windows 10 style the pointer carries a light. Move the mouse over this "
         "window to feel how strong the current setting is.",
         "Windows 10 スタイルではマウスに光が追従します。"
         "このウィンドウ上でマウスを動かすと、現在の強さを確かめられます。"),
    "界面文字的显示语言。选「跟随系统」就跟着 Windows 的显示语言走。":
        ("介面文字的顯示語言。選「跟隨系統」就跟著 Windows 的顯示語言走。",
         "The language of the interface. “Follow system” tracks the Windows display "
         "language.",
         "UI の表示言語です。「システムに従う」を選ぶと Windows の表示言語に追従します。"),
    "都设置好了": ("都設定好了", "All set", "設定完了"),
    "这些选项随时可以在设置里修改，也可以再运行一次这个引导。":
        ("這些選項隨時可以在設定裡修改，也可以再執行一次這個引導。",
         "You can change any of this in Settings, or run this guide again.",
         "これらの設定は設定画面でいつでも変更できます。"
         "このガイドを再度実行することもできます。"),
    "界面风格：{0}": ("介面風格：{0}", "Interface style: {0}", "インターフェイス: {0}"),
    "主题：{0}": ("主題：{0}", "Theme: {0}", "テーマ: {0}"),
    "背景材质：{0}": ("背景材質：{0}", "Backdrop: {0}", "背景: {0}"),
    "光效强度：{0}": ("光效強度：{0}", "Pointer light: {0}", "光の強さ: {0}"),
    "界面语言：{0}": ("介面語言：{0}", "Language: {0}", "表示言語: {0}"),
    "切换背景材质后，新打开的窗口会使用它":
        ("切換背景材質後，新開啟的視窗會使用它",
         "A new backdrop applies to windows opened from now on",
         "背景の変更は、これ以降に開くウィンドウに適用されます"),
    "切换后立即生效，无需重启":
        ("切換後立即生效，無需重新啟動",
         "Applies immediately; no restart needed",
         "すぐに反映されます。再起動は不要です"),
    "本机编码速度跟不上：实际录制 {0:.1f}s，写入成片 {1:.1f}s（少 {2:.1f}s）。建议降低帧率或缩小录制区域。":
        ("本機編碼速度跟不上：實際錄製 {0:.1f}s，寫入成片 {1:.1f}s（少 {2:.1f}s）。"
         "建議降低影格速率或縮小錄製區域。",
         "The encoder cannot keep up: recorded {0:.1f}s but wrote {1:.1f}s "
         "(missing {2:.1f}s). Lower the frame rate or record a smaller area.",
         "エンコードが追いつきません: 録画 {0:.1f}s に対して書き出し {1:.1f}s"
         "（{2:.1f}s 不足）。フレーム レートを下げるか範囲を狭めてください。"),
    "回环设备 (What U Hear / 立体声混音 / VoiceMeeter)":
        ("回環裝置 (What U Hear / 立體聲混音 / VoiceMeeter)",
         "Loopback devices (What U Hear / Stereo Mix / VoiceMeeter)",
         "ループバック デバイス (What U Hear / ステレオ ミキサー / VoiceMeeter)"),
    "需要“立体声混音”等回环设备；Windows 10 默认未启用":
        ("需要「立體聲混音」等回環裝置；Windows 10 預設未啟用",
         "Needs a loopback device such as Stereo Mix; not enabled by default on Windows 10",
         "ステレオ ミキサーなどのループバック デバイスが必要です。Windows 10 では既定で無効です"),
    "未找到立体声混音等回环设备。可在“声音设置”中启用“立体声混音”。":
        ("未找到立體聲混音等回環裝置。可在「音效設定」中啟用「立體聲混音」。",
         "No loopback device such as Stereo Mix. Enable “Stereo Mix” in Sound settings.",
         "ステレオ ミキサーなどのループバック デバイスがありません。サウンド設定で有効にしてください。"),
    "选择要录制的输入设备": ("選擇要錄製的輸入裝置", "Choose the input device to record",
                              "録音する入力デバイスを選択"),
    "无法在录制中切换麦克风": ("無法在錄製中切換麥克風",
                                "Cannot switch microphones while recording",
                                "録画中はマイクを切り替えられません"),
    "无法录制系统声音": ("無法錄製系統聲音", "Cannot record system audio",
                          "システム音声を録音できません"),
    "录制时可将": ("錄製時可將", "While recording, ", "録画中は"),
    "录制时将": ("錄製時將", "While recording, ", "録画中は"),
    "录制鼠标光标": ("錄製滑鼠游標", "Record the mouse cursor", "マウス カーソルを録画"),
    "录制鼠标指针": ("錄製滑鼠指標", "Record the mouse pointer", "マウス ポインターを録画"),
    "在画面中绘制鼠标指针": ("在畫面中繪製滑鼠指標", "Draws the cursor into the video",
                              "映像にカーソルを描画します"),
    "在视频中混入麦克风声音": ("在視訊中混入麥克風聲音", "Mixes the microphone into the video",
                                "映像にマイク音声を混ぜます"),
    "录制时将 ": ("錄製時將 ", "While recording, ", "録画中は"),
    "快捷键": ("快速鍵", "Hotkeys", "ホットキー"),
    "截图快捷键": ("截圖快速鍵", "Screenshot hotkey", "スクリーンショットのホットキー"),
    "录屏快捷键": ("錄影快速鍵", "Recording hotkey", "録画のホットキー"),
    "若被系统占用，程序会自动回退到备用组合":
        ("若被系統占用，程式會自動退回備用組合",
         "Falls back to an alternative if Windows already uses it",
         "Windows が使用中の場合は代替キーに自動で切り替わります"),
    "截图工具 (Windows 11) 会占用 Win+Shift+R":
        ("截圖工具 (Windows 11) 會占用 Win+Shift+R",
         "The Snipping Tool (Windows 11) takes Win+Shift+R",
         "切り取りツール (Windows 11) が Win+Shift+R を使用します"),
    "按 Win+Shift+S 截图，Win+Shift+R 录屏；右键托盘图标退出":
        ("按 Win+Shift+S 截圖，Win+Shift+R 錄影；右鍵點匣圖示結束",
         "Win+Shift+S to capture, Win+Shift+R to record; right-click the tray icon to exit",
         "Win+Shift+S でキャプチャ、Win+Shift+R で録画。終了は通知領域の右クリックから"),
    "按 Ctrl+Alt+Q 停止录制，Ctrl+Alt+P 暂停/继续":
        ("按 Ctrl+Alt+Q 停止錄製，Ctrl+Alt+P 暫停/繼續",
         "Ctrl+Alt+Q stops recording, Ctrl+Alt+P pauses or resumes",
         "Ctrl+Alt+Q で停止、Ctrl+Alt+P で一時停止/再開"),
    "停止录制 (Ctrl+Alt+Q)": ("停止錄製 (Ctrl+Alt+Q)", "Stop recording (Ctrl+Alt+Q)",
                              "録画を停止 (Ctrl+Alt+Q)"),
    "暂停 (Ctrl+Alt+P)": ("暫停 (Ctrl+Alt+P)", "Pause (Ctrl+Alt+P)", "一時停止 (Ctrl+Alt+P)"),
    "继续 (Ctrl+Alt+P)": ("繼續 (Ctrl+Alt+P)", "Resume (Ctrl+Alt+P)", "再開 (Ctrl+Alt+P)"),
    "取消并删除这段录制": ("取消並刪除此段錄製", "Cancel and delete this recording",
                            "キャンセルしてこの録画を削除"),
    "选择捕获区域": ("選擇擷取區域", "Choose the capture area", "キャプチャ範囲を選択"),
    "矩形区域": ("矩形區域", "Rectangle", "四角形"),
    "窗口": ("視窗", "Window", "ウィンドウ"),
    "全屏": ("全螢幕", "Full screen", "全画面"),
    "自由绘制": ("自由繪製", "Freehand", "フリーハンド"),
    "拖动以选择区域 · Esc 取消": ("拖曳以選擇區域 · Esc 取消",
                                  "Drag to select an area · Esc to cancel",
                                  "ドラッグで範囲を選択 · Esc でキャンセル"),
    "框选后需要确认": ("框選後需要確認", "Confirm the selection before capturing",
                        "範囲を選んでから確定します"),
    "关闭时与 Windows 11 一致：松开鼠标立即开始；打开后可用手柄调整区域，按确认或回车才开始":
        ("關閉時與 Windows 11 一致：放開滑鼠立即開始；開啟後可用控點調整區域，按確認或 Enter 才開始",
         "Off matches Windows 11: capture starts on mouse-up. On: adjust with the handles, "
         "then confirm or press Enter.",
         "オフは Windows 11 と同じでマウスを離すと即開始。オンではハンドルで調整し、"
         "確定または Enter で開始します。"),
    "选择要录制的区域": ("選擇要錄製的區域", "Choose the area to record", "録画する範囲"),
    "开始录屏": ("開始錄影", "Start recording", "録画を開始"),
    "开始截图": ("開始截圖", "Take a screenshot", "スクリーンショットを撮る"),
    "录屏已开始": ("錄影已開始", "Recording started", "録画を開始しました"),
    "已取消录制": ("已取消錄製", "Recording cancelled", "録画をキャンセルしました"),
    "录制已保存": ("錄製已儲存", "Recording saved", "録画を保存しました"),
    "正在录制中": ("正在錄製中", "Recording", "録画中"),
    "已关闭": ("已關閉", "Closed", "閉じました"),
    "无法启动捕获": ("無法啟動擷取", "Could not start capture", "キャプチャを開始できません"),
    "无法读取屏幕内容": ("無法讀取螢幕內容", "Could not read the screen",
                          "画面を読み取れません"),
    "PNG 编码失败": ("PNG 編碼失敗", "PNG encoding failed", "PNG のエンコードに失敗"),
    "录制出现问题": ("錄製發生問題", "Something went wrong while recording",
                      "録画中に問題が発生しました"),
    "请查看日志 %APPDATA%\\WinSnipRec\\app.log":
        ("請查看日誌 %APPDATA%\\WinSnipRec\\app.log",
         "See %APPDATA%\\WinSnipRec\\app.log",
         "%APPDATA%\\WinSnipRec\\app.log を確認してください"),
    "PNG 图片 (*.png);;JPEG 图片 (*.jpg)":
        ("PNG 圖片 (*.png);;JPEG 圖片 (*.jpg)",
         "PNG image (*.png);;JPEG image (*.jpg)",
         "PNG 画像 (*.png);;JPEG 画像 (*.jpg)"),
    "请先停止录制，然后在工具栏中选择声音来源":
        ("請先停止錄製，然後在工具列中選擇聲音來源",
         "Stop the recording first, then pick the audio source in the toolbar",
         "先に録画を停止し、ツール バーで音声ソースを選んでください"),
    "恢复默认": ("恢復預設", "Restore defaults", "既定に戻す"),
    "已恢复默认设置": ("已恢復預設設定", "Defaults restored", "既定に戻しました"),
    "临时文件已删除": ("暫存檔案已刪除", "Temporary files deleted", "一時ファイルを削除しました"),
    "最大": ("最大", "Max", "最大"),
    "还原": ("還原", "Restore", "元に戻す"),
    "最小化": ("最小化", "Minimize", "最小化"),
    "最大化": ("最大化", "Maximize", "最大化"),
    "关于截图工具": ("關於截圖工具", "About WinSnipRec", "WinSnipRec について"),
    "在 Windows 10 上重现 Windows 11 截图工具的录屏体验。\n"
    "区域 / 窗口 / 全屏录制 · 暂停继续 · 麦克风与系统声音 · H.264 MP4 输出。\n"
    "界面、图标与配色按 Windows 11 Fluent 设计规范绘制。":
        ("在 Windows 10 上重現 Windows 11 截圖工具的錄影體驗。\n"
         "區域 / 視窗 / 全螢幕錄製 · 暫停繼續 · 麥克風與系統聲音 · H.264 MP4 輸出。\n"
         "介面、圖示與配色依 Windows 11 Fluent 設計規範繪製。",
         "Brings the Windows 11 Snipping Tool recording experience to Windows 10.\n"
         "Region / window / full-screen · pause and resume · microphone and system audio · "
         "H.264 MP4.\nThe interface, icons and palette follow Windows 11 Fluent.",
         "Windows 11 の切り取りツールの録画体験を Windows 10 で再現します。\n"
         "範囲 / ウィンドウ / 全画面 · 一時停止と再開 · マイクとシステム音声 · H.264 MP4。\n"
         "UI、アイコン、配色は Windows 11 Fluent に準拠しています。"),
}


def _normalise(code: str) -> str:
    return (code or "").replace("_", "-").lower()


def resolve(requested: str | None = None) -> str:
    """Turn a setting (possibly "system") into a concrete language code."""
    value = _normalise(requested or "system")
    if value == "system":
        return _system_language()
    for code, _label in LANGUAGES:
        if _normalise(code) == value:
            return code
    # Accept bare prefixes such as "zh", "en-US", "ja-JP".
    if value.startswith("zh"):
        if any(tag in value for tag in ("hant", "tw", "hk", "mo")):
            return "zh-Hant"
        return "zh-Hans"
    if value.startswith("ja"):
        return "ja"
    if value.startswith("en"):
        return "en"
    return "zh-Hans"


def _system_language() -> str:
    """Map the OS locale onto a supported language."""
    tag = ""
    try:
        from PySide6.QtCore import QLocale

        tag = _normalise(QLocale.system().name())
    except Exception:
        tag = ""
    if not tag:
        try:
            import locale

            tag = _normalise(locale.getdefaultlocale()[0] or "")
        except Exception:
            tag = ""
    return resolve(tag) if tag else "zh-Hans"


_current: str | None = None


def language() -> str:
    """The language in use, resolved once and cached."""
    global _current
    if _current is None:
        try:
            from .settings import settings

            _current = resolve(getattr(settings, "language", "system"))
        except Exception:
            _current = _system_language()
    return _current


def set_language(code: str) -> None:
    global _current
    _current = resolve(code)
    log.info("interface language -> %s", _current)


def available() -> list[tuple[str, str]]:
    """(code, label) pairs for the settings dropdown."""
    return list(LANGUAGES)


def t(text: str) -> str:
    """Translate a Simplified Chinese source string.

    Unknown strings fall back to the source, so a missed entry shows Chinese
    rather than an empty label or a key.
    """
    if not text:
        return text
    code = language()
    if code == "zh-Hans":
        return text
    entry = TABLE.get(text)
    if entry is None:
        return text
    index = TRANSLATED.index(code)
    translated = entry[index]
    return translated or text


def translate_all(text: str) -> dict[str, str]:
    """Every language's rendering of one string (used by the tests)."""
    return {code: (text if code == "zh-Hans" else (TABLE.get(text) or (text, text, text))[
        TRANSLATED.index(code)]) for code in ("zh-Hans",) + TRANSLATED}
