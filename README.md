[简体中文](README.md) | [繁体中文](README_CHT.md) | [English](README_ENG.md)

# 模拟权杖 | Simulated_Scepter
模拟权杖 ω - u13.exe
本软件使用 [AGPL 3.0 协议](https://github.com/syfoud/Simulated_Scepter/LICENSE)开源.

《崩坏:星穹铁道》的极难成就《铁血战士》自动助手，一键自动化助力完成。
![模拟宇宙](doc/insect.png)
![模拟宇宙](doc/warrior.png)
 软件基于图像识别，不支持任何非绿色作弊功能（如抓包，逆向）。

 在提问之前。。。你需要查看的 [How to ask](https://github.com/ryanhanwu/How-To-Ask-Questions-The-Smart-Way/blob/main/README.md)


----------------------------------------------------------------------------------------------

# 免责声明 | Disclaimer

### 一、软件性质与开源声明
本软件是一个外部开源辅助工具，旨在通过模拟用户操作、与游戏现有用户界面（UI）进行交互，以实现游戏玩法的自动化。本软件被设计成仅通过现有用户界面与游戏交互，不会以任何方式修改任何游戏文件或游戏代码。本软件开源、免费，仅供个人学习、交流与研究自动化技术之用。开发者团队拥有本项目的最终解释权。

### 二、知识产权与权属声明
《崩坏：星穹铁道》游戏及其相关内容的著作权、商标权等一切知识产权，均归米哈游公司（miHoYo）及其关联实体合法所有。本软件仅作为技术学习工具，不主张、不享有任何游戏内容的版权。

### 三、用户使用许可范围
用户通过本软件获取的全部功能，均被严格限定为“个人临时学习研究”之唯一目的，不构成对用户任何明示或默示的商业使用授权。用户不得将本软件以任何形式直接或间接用于商业盈利、推广、培训、代练收费等场景。

### 四、用户义务与合规风险提示
4.1 用户使用本软件时需遵守国家相关法律法规及米哈游官方发布的用户协议。用户在使用本软件前，已充分知悉并理解米哈游在其 [《崩坏：星穹铁道》公平游戏宣言](https://sr.mihoyo.com/news/111246?nav=news&type=notice) 中的明确规定：

> “严禁使用外挂、加速器、脚本或其他破坏游戏公平性的第三方工具。”
> “一经发现，米哈游（下亦称‘我们’）将视违规严重程度及违规次数，采取扣除违规收益、冻结游戏账号、永久封禁游戏账号等措施。”

4.2 用户完全知晓并同意，使用本软件可能会被米哈游认定为违反上述规定的行为，并可能导致游戏账号遭受包括但不限于警告、收益扣除、暂时冻结乃至永久封禁在内的处罚。由此产生的一切后果与责任，均由用户单方承担。

### 五、第三方代练风险提示
若用户遇到商家使用本软件进行代练并收费，请注意：该等商家收取的费用，可能为设备损耗、时间成本等费用，与软件本身无关。因接受此类代练服务产生的一切问题、纠纷及后果，包括但不限于账号被封禁、虚拟财产损失、个人信息泄露或被商家欺诈等，均与本软件及开发者团队无任何关联。

### 六、风险自担与责任豁免
6.1 运营方/开发者团队对软件的功能可用性、稳定性、安全性、兼容性及无瑕疵运行，不作任何形式的明示或默示担保。

6.2 用户因获取、使用本软件而遭受的任何直接或间接损失、法律纠纷、设备损害、数据丢失、游戏账号被处罚或其他风险，无论因何由致，均由用户自行承担全部责任，运营方/开发者团队概不负责。

6.3 运营方/开发者团队不对用户的使用行为承担任何监督、担保、调解或赔偿义务。使用本软件产生的所有问题与本项目及开发者团队无关。

6.4 用户任何违反本协议使用限制及法律法规规定的行为，均构成违约。用户须独立承担由此引发的一切民事、行政乃至刑事责任，并赔偿因此给运营方/开发者团队或其他第三方造成的全部损失。

### 七、协议生效与最终解释
用户下载、安装或使用本软件之行为，即构成对本协议全部条款的完全了解与不可撤销的同意。本协议各条款之最终解释权及软件的运营管理权，均归属开发者团队。开发者团队有权在必要时单方变更本协议内容或终止服务，无需事先逐一通知用户。

----------------------------------------------------------------------------------------------

# 功能 | Function

## 智能择路  

![image](doc/select.png)

## 精准索敌  

![image](doc/battle.png)

## 进阶功能

### 视频录制  

以爱的名义，将逝去的一切尽数珍藏。。。

### 提前重置  

若此世无法带来拯救，那就为它带来毁灭。。。（人话：40杀达成希望渺茫则重开）

## 地图频率分析
```plaintext
sqlite3 config/backup/map_visits.db "SELECT * FROM map_visits ORDER BY visit_count DESC;"
```

## 节点日志查询
```plaintext
sqlite3 config/backup/node_log.db "SELECT id, created_at, json_extract(data, '$.area') AS area, json_extract(data, '$.event') AS event, json_extract(data, '$.plane_floor') AS plane_floor FROM node_log ORDER BY id DESC;"
```

## 事件日志查询(emergency)
```plaintext
sqlite3 config/backup/emergency.db "SELECT id, created_at, json_extract(data, '$.count') AS count, json_extract(data, '$.node_count') AS node_count, json_extract(data, '$.event') AS event, json_extract(data, '$.plane_floor') AS plane_floor FROM node_log ORDER BY id DESC;"
sqlite3 config/backup/emergency.db "DELETE FROM node_log;"
```
----------------------------------------------------------------------------------------------

## 兼容性

只支持1080p及以上屏幕(x>=1920,窗口化或全屏幕)，关闭hdr，文本语言选择简体中文，游戏界面不能有任何遮挡,需置于前台。

由于onnxruntime环境，电脑环境需注意win10版本是否大于等于2004，win11默认支持 ，同时建议具有2G以上显存运行本软件

下载解压目录不允许有中文路径！！
# 下载 | Download 
方法一：前往交流群直接下载打包好的发行版（推荐）* ![](https://img.shields.io/badge/QQ%201群[已满]-1072802257-4e4c97)* ![](https://img.shields.io/badge/QQ%202群-870863632-4e4c97)

方法二：自行下载源码本地部署，没接触过python的，请忽视下述教程，可以直接前往交流群下载相关资源

**快速部署**

```plaintext
uv sync
uv run new_gui.py
```
----------------------------------------------------------------------------------------------

# 相关配置建议

一号位角色建议顺序为白厄、黄泉、其它远程平a角色,其余序号使用角色任意，队伍需至少3人方能正常运行脚本

请注意！！！！！ 开始运行/开始校准之后就不要移动游戏窗口了！避免脚本错误的执行！！要移动请先按f5停止自动化！

### 校准

有时可能出现视角转动过大/过小而导致迷路的问题，可以尝试手动校准：

进入游戏，将人物传送到黑塔的办公室，然后gui点击校准角度按钮，等待视角转换/原地转圈结束

改变鼠标dpi可能会影响校准值，此时需要重新校准。

## GUI使用方法

**第一次运行**

按照下述系统设置配图调整自己的系统设置，在游戏中设置“自动沿用战斗设置”，在寰宇蝗灾界面的毁灭的配队中选好队伍角色

**运行权杖**

点击”擢升铁血战士“运行

注意！！！！！ 开始运行/开始校准之后就不要移动游戏窗口了！要移动请先停止自动化！

F5/‘停止任务’按钮停止运行。

**系统设置**

![画质](doc/config.png)



----------------------------------------------------------------------------------------------

# 开发交流-玩家社区-助力毁灭 | Destruction
* 包含本权杖系统稳定发行版.
* ![](https://img.shields.io/badge/QQ%201群-1072802257-4e4c97)

----------------------------------------------------------------------------------------------

# 支持开发 | Star or Buy Coffee

### 点Star - 觉得本项目有帮助请右上角点一个免费的Star喵, 谢谢喵

### 微信打赏

<img alt="image" height="300" src="doc/pay.jpg" width="300"/>


# 致谢 | Acknowledgements

本项目使用了以下优秀的开源库和工具：

## 核心依赖库

- **[OpenCV](https://opencv.org/)** - 图像处理和计算机视觉库，用于图像识别、模板匹配和小地图分析
- **[NumPy](https://numpy.org/)** - 科学计算库，提供高效的数组操作和数值计算支持（OpenCV依赖）
- **[Pillow](https://python-pillow.org/)** - Python图像处理库，用于图像加载和处理
- **[PyAutoGUI](https://pyautogui.readthedocs.io/)** - 自动化控制库，实现鼠标键盘的模拟操作
- **[pywin32](https://github.com/mhammond/pywin32)** - Windows API接口，用于窗口管理和系统级操作
- **[keyboard](https://github.com/boppreh/keyboard)** - 全局键盘监听和控制库

## OCR与深度学习

- **[ONNX Runtime](https://onnxruntime.ai/)** - 跨平台机器学习推理引擎，支持DirectML加速，用于PaddleOCR模型推理

## GUI框架

- **[PyQt5](https://www.riverbankcomputing.com/software/pyqt/)** - Qt框架的Python绑定，构建图形用户界面

## 数据处理与配置

- **[PyYAML](https://pyyaml.org/)** - YAML解析器，用于配置文件管理
- **[Shapely](https://shapely.readthedocs.io/)** - 几何对象操作库，用于空间分析和路径规划
- **[pyclipper](https://github.com/greginvm/pyclipper)** - 多边形裁剪库，配合OCR使用
- **[SciPy](https://scipy.org/)** - 科学计算库，用于信号处理和小地图分析
- **[Matplotlib](https://matplotlib.org/)** - 数据可视化库，用于调试和数据分析（开发/测试依赖）
- **[ipykernel](https://ipython.org/)** - Jupyter内核支持（开发/测试依赖）

## 相关开源项目
- **[Auto_Simulated_Universe](https://github.com/CHNZYX/Auto_Simulated_Universe/)** - 本项目核心轮子，基于此项目大幅重构
- **[StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot/)** - 先进的状态机架构启发，地图高精度定位

## 特别鸣谢
### 贡献者

感谢以下贡献者对本项目做出的贡献

<a>

  <img src="https://contrib.rocks/image?repo=syfoud/Simulated_Scepter" />

</a>

### 所有赞助者

您的支持就是作者开发和维护项目的动力！

### And 每一位点star支持的你：
[![Star History](https://api.star-history.com/svg?repos=syfoud/Simulated_Scepter&type=Date)](https://star-history.com/#syfoud/Simulated_Scepter&Date)