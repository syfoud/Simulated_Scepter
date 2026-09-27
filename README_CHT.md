[简体中文](README.md) | [繁體中文](README_CHT.md) | [English](README_ENG.md)

# 模擬權杖 | Simulated_Scepter
模擬權杖 ω - u13.exe
本軟體使用 [AGPL 3.0 協議](https://github.com/syfoud/Simulated_Scepter/LICENSE)開源。

《崩壞：星穹鐵道》的寰宇蝗災極難成就自動助手，一鍵自動化助力完成。
![模擬宇宙](doc/insect.png)
![模擬宇宙](doc/warrior.png)
 軟體基於圖像識別，不支援任何非綠色作弊功能（如抓包，逆向）。


----------------------------------------------------------------------------------------------

# 免責聲明 | Disclaimer

### 一、軟體性質與開源聲明
本軟體是一個外部開源輔助工具，旨在透過模擬使用者操作、與遊戲現有使用者介面（UI）進行互動，以實現遊戲玩法的自動化。本軟體被設計成僅透過現有使用者介面與遊戲互動，不會以任何方式修改任何遊戲檔案或遊戲程式碼。本軟體開源、免費，僅供個人學習、交流與研究自動化技術之用。開發者團隊擁有本專案的最終解釋權。

### 二、智慧財產權與權屬聲明
《崩壞：星穹鐵道》遊戲及其相關內容的著作權、商標權等一切智慧財產權，均歸米哈遊公司（miHoYo）及其關聯實體合法所有。本軟體僅作為技術學習工具，不主張、不享有任何遊戲內容的版權。

### 三、使用者使用許可範圍
使用者透過本軟體獲取的全部功能，均被嚴格限定為「個人臨時學習研究」之唯一目的，不構成對使用者任何明示或默示的商業使用授權。使用者不得將本軟體以任何形式直接或間接用於商業盈利、推廣、培訓、代練收費等場景。

### 四、使用者義務與合規風險提示
4.1 使用者使用本軟體時需遵守國家相關法律法規及米哈遊官方發佈的使用者協議。使用者在使用本軟體前，已充分知悉並理解米哈遊在其 [《崩壞：星穹鐵道》公平遊戲宣言](https://sr.mihoyo.com/news/111246?nav=news&type=notice) 中的明確規定：

> 「嚴禁使用外掛、加速器、腳本或其他破壞遊戲公平性的第三方工具。」
> 「一經發現，米哈遊（下亦稱『我們』）將視違規嚴重程度及違規次數，採取扣除違規收益、凍結遊戲帳號、永久封禁遊戲帳號等措施。」

4.2 使用者完全知曉並同意，使用本軟體可能會被米哈遊認定為違反上述規定的行為，並可能導致遊戲帳號遭受包括但不限於警告、收益扣除、暫時凍結乃至永久封禁在內的處罰。由此產生的一切後果與責任，均由使用者單方承擔。

### 五、第三方代練風險提示
若使用者遇到商家使用本軟體進行代練並收費，請注意：該等商家收取的費用，可能為設備損耗、時間成本等費用，與軟體本身無關。因接受此類代練服務產生的一切問題、糾紛及後果，包括但不限於帳號被封禁、虛擬財產損失、個人資訊洩露或被商家詐欺等，均與本軟體及開發者團隊無任何關聯。

### 六、風險自擔與責任豁免
6.1 營運方/開發者團隊對軟體的功能可用性、穩定性、安全性、相容性及無瑕疵運行，不作任何形式的明示或默示擔保。

6.2 使用者因獲取、使用本軟體而遭受的任何直接或間接損失、法律糾紛、設備損害、資料遺失、遊戲帳號被處罰或其他風險，無論因何由致，均由使用者自行承擔全部責任，營運方/開發者團隊概不負責。

6.3 營運方/開發者團隊不對使用者的使用行為承擔任何監督、擔保、調解或賠償義務。使用本軟體產生的所有問題與本專案及開發者團隊無關。

6.4 使用者任何違反本協議使用限制及法律法規規定的行為，均構成違約。使用者須獨立承擔由此引發的一切民事、行政乃至刑事責任，並賠償因此給營運方/開發者團隊或其他第三方造成的全部損失。

### 七、協議生效與最終解釋
使用者下載、安裝或使用本軟體之行為，即構成對本協議全部條款的完全了解與不可撤銷的同意。本協議各條款之最終解釋權及軟體的營運管理權，均歸屬開發者團隊。開發者團隊有權在必要時單方變更本協議內容或終止服務，無需事先逐一通知使用者。

----------------------------------------------------------------------------------------------

# 功能 | Function

## 智能擇路  

![image](doc/select.png)

## 精準索敵  

![image](doc/battle.png)

## 鐵血戰士
![image](doc/iron_blood.png)

## 彈指一揮(絕讚測試中)
![image](doc/finger_snap.png)

## 進階功能

### 影片錄製  

以愛的名義，她將逝去的一切盡數珍藏。。。直到時間的盡頭
![image](doc/end.png)
至少，這樣的結局足夠溫柔
### 提前輪迴  

若此世無法帶來拯救，那就為它帶來毀滅。。。（極低機率達成40殺則立即重開）
![image](doc/retry.png)
## 地圖頻率分析
```plaintext
sqlite3 config/backup/map_visits.db "SELECT * FROM map_visits ORDER BY visit_count DESC;"
```

## 節點日誌查詢
```plaintext
sqlite3 config/backup/node_log.db "SELECT id, created_at, json_extract(data, '$.area') AS area, json_extract(data, '$.event') AS event, json_extract(data, '$.plane_floor') AS plane_floor FROM node_log ORDER BY id DESC;"
```

## 事件日誌查詢(emergency)
```plaintext
sqlite3 config/backup/emergency.db "SELECT id, created_at, json_extract(data, '$.count') AS count, json_extract(data, '$.node_count') AS node_count, json_extract(data, '$.event') AS event, json_extract(data, '$.plane_floor') AS plane_floor FROM node_log ORDER BY id DESC;"
sqlite3 config/backup/emergency.db "DELETE FROM node_log;"
```

## 解除安裝

資料夾全部刪除即可
![image](doc/delete.png)
然後。。。就走向明天吧


----------------------------------------------------------------------------------------------

## 相容性

保留原有 1920×1080 遊戲畫面支援；本次新增適配僅限本機遊戲 **4K（3840×2160）**，須**關閉 DLAA 和反鋸齒**。關閉 HDR，文字語言選擇簡體中文，遊戲介面不能有任何遮擋，需置於前景。其他解析度不屬於本次新增適配範圍，雲端遊戲仍沿用原有 1080p 規則。使用條件與驗證範圍見 [4K 適配說明](docs/4k-adaptation.md)。

由於onnxruntime環境，電腦環境需注意win10版本是否大於等於2004，win11預設支援 ，同時建議具有2G以上顯存運行本軟體

下載解壓目錄不允許有中文路徑！！
# 下載 | Download 
方法一：直接下載打包好的發行版（推薦）* ![](https://img.shields.io/badge/QQ%201群[開發意向優先]-1072802257-4e4c97)* ![](https://img.shields.io/badge/QQ%202群-870863632-4e4c97)

方法二：自行下載原始碼本地部署，沒接觸過python的，請忽視下述教程，可以直接前往交流群下載相關資源

**快速部署**

```plaintext
uv sync
uv run new_gui.py
```
----------------------------------------------------------------------------------------------

# 相關配置建議

一號位角色建議順序為白厄、黃泉、銀狼LV.999、其它遠程平a角色,其餘序號使用角色任意，隊伍需至少3人方能正常運行腳本

請注意！！！！！ 開始運行/開始校準之後就不要移動遊戲視窗了！避免腳本錯誤的執行！！要移動請先按f5停止自動化！

### 校準

有時可能出現視角轉動過大/過小而導致迷路的問題，可以嘗試手動校準：

進入遊戲，將人物傳送到黑塔的辦公室，然後gui點擊校準角度按鈕，等待視角轉換/原地轉圈結束

改變滑鼠dpi可能會影響校準值，此時需要重新校準。

## GUI使用方法

**第一次運行**

按照下述系統設定配圖調整自己的系統設定，在遊戲中設定「自動沿用戰鬥設定」，在寰宇蝗災介面的毀滅的配隊中選好隊伍角色

**運行權杖**

點擊」擢升鐵血戰士「運行

注意！！！！！ 開始運行/開始校準之後就不要移動遊戲視窗了！要移動請先停止自動化！

F5/『停止任務』按鈕停止運行。

**系統設定**

![畫質](doc/config.png)



----------------------------------------------------------------------------------------------

# 開發交流-玩家社群-助力毀滅 | Destruction
* 包含本權杖系統穩定發行版.
* ![](https://img.shields.io/badge/QQ%201群[開發意向優先]-1072802257-4e4c97)
![](https://img.shields.io/badge/QQ%202群-870863632-4e4c97)
----------------------------------------------------------------------------------------------

# 支援開發 | Star or Buy Coffee

### 點Star - 覺得本專案有幫助請右上角點一個免費的Star喵, 謝謝喵

### 微信打賞

<img alt="image" height="300" src="doc/pay.jpg" width="300"/>


# 致謝 | Acknowledgements

本專案使用了以下優秀的開源庫和工具：

## 核心依賴庫

- **[OpenCV](https://opencv.org/)** - 圖像處理和電腦視覺庫，用於圖像識別、模板匹配和小地圖分析
- **[NumPy](https://numpy.org/)** - 科學計算庫，提供高效的陣列操作和數值計算支援（OpenCV依賴）
- **[Pillow](https://python-pillow.org/)** - Python圖像處理庫，用於圖像載入和處理
- **[PyAutoGUI](https://pyautogui.readthedocs.io/)** - 自動化控制庫，實現滑鼠鍵盤的模擬操作
- **[pywin32](https://github.com/mhammond/pywin32)** - Windows API介面，用於視窗管理和系統級操作
- **[keyboard](https://github.com/boppreh/keyboard)** - 全域鍵盤監聽和控制庫

## OCR與深度學習

- **[ONNX Runtime](https://onnxruntime.ai/)** - 跨平台機器學習推理引擎，支援DirectML加速，用於PaddleOCR模型推理

## GUI框架

- **[PyQt5](https://www.riverbankcomputing.com/software/pyqt/)** - Qt框架的Python綁定，建構圖形使用者介面

## 資料處理與配置

- **[PyYAML](https://pyyaml.org/)** - YAML解析器，用於設定檔管理
- **[Shapely](https://shapely.readthedocs.io/)** - 幾何物件操作庫，用於空間分析和路徑規劃
- **[pyclipper](https://github.com/greginvm/pyclipper)** - 多邊形裁剪庫，配合OCR使用
- **[SciPy](https://scipy.org/)** - 科學計算庫，用於訊號處理和小地圖分析
- **[Matplotlib](https://matplotlib.org/)** - 資料視覺化庫，用於除錯和資料分析（開發/測試依賴）
- **[ipykernel](https://ipython.org/)** - Jupyter核心支援（開發/測試依賴）

## 相關開源專案
- **[Auto_Simulated_Universe](https://github.com/CHNZYX/Auto_Simulated_Universe/)** - 本專案核心輪子，基於此專案大幅重構
- **[StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot/)** - 先進的狀態機架構啟發，地圖高精度定位

## 特別鳴謝
### 貢獻者

感謝以下貢獻者對本專案做出的貢獻

<a>

  <img src="https://contrib.rocks/image?repo=syfoud/Simulated_Scepter" />

</a>

### 所有贊助者

您的支持就是作者開發和維護專案的動力！

### And 每一位點star支持的你：
[![Star History](https://star-history.dera.page/svg?repos=syfoud/Simulated_Scepter&type=Date)](https://star-history.dera.page/#syfoud/Simulated_Scepter&Date)
