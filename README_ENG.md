[简体中文](README.md) | [繁體中文](README_CHT.md) | [English](README_ENG.md)

# Simulated Scepter | Simulated_Scepter
Simulated Scepter ω - u13.exe
This software is open-sourced under the [AGPL 3.0 License](https://github.com/syfoud/Simulated_Scepter/LICENSE).

An automated assistant for the ultra-difficult achievement in the Swarm Disaster of "Honkai: Star Rail", providing one-click automation to help you complete it.
![Simulated Universe](doc/insect.png)
![image](doc/iron_blood.png)
 The software is based on image recognition and does not support any non-legitimate cheating functions (such as packet capture, reverse engineering).


----------------------------------------------------------------------------------------------

# Disclaimer

### 1. Software Nature and Open Source Statement
This software is an external open-source auxiliary tool designed to automate gameplay by simulating user operations and interacting with the game's existing user interface (UI). This software is designed to interact with the game only through the existing user interface and will not modify any game files or game code in any way. This software is open-source and free, intended solely for personal learning, communication, and research into automation technology. The developer team reserves the final interpretation rights of this project.

### 2. Intellectual Property and Ownership Statement
All intellectual property rights, including copyrights and trademarks, of the game "Honkai: Star Rail" and its related content legally belong to miHoYo and its affiliated entities. This software serves only as a technical learning tool and does not claim or enjoy any copyright of the game content.

### 3. Scope of User License
All functions obtained through this software are strictly limited to the sole purpose of "personal temporary learning and research" and do not constitute any express or implied commercial use authorization for users. Users shall not use this software in any form, directly or indirectly, for commercial profit, promotion, training, paid boosting services, or other similar scenarios.

### 4. User Obligations and Compliance Risk Warning
4.1 When using this software, users must comply with national laws and regulations and the user agreement published by miHoYo. Before using this software, users have fully understood and acknowledged the clear provisions in miHoYo's ["Honkai: Star Rail" Fair Play Declaration](https://sr.mihoyo.com/news/111246?nav=news&type=notice):

> "The use of cheats, accelerators, scripts, or other third-party tools that disrupt game fairness is strictly prohibited."
> "Once discovered, miHoYo (hereinafter referred to as 'we') will take measures such as deducting illegal gains, freezing game accounts, or permanently banning game accounts, depending on the severity and frequency of violations."

4.2 Users fully understand and agree that using this software may be considered by miHoYo as a violation of the above regulations, which may result in penalties including but not limited to warnings, deduction of gains, temporary suspension, or even permanent ban of the game account. All consequences and responsibilities arising therefrom shall be borne solely by the user.

### 5. Third-Party Boosting Service Risk Warning
If users encounter merchants using this software for paid boosting services, please note: the fees charged by such merchants may be for equipment wear and tear, time costs, etc., and are unrelated to the software itself. All problems, disputes, and consequences arising from accepting such boosting services, including but not limited to account bans, loss of virtual property, personal information leakage, or fraud by merchants, are not associated with this software or the developer team.

### 6. Risk Assumption and Liability Exemption
6.1 The operator/developer team makes no express or implied warranties of any kind regarding the functional availability, stability, security, compatibility, or error-free operation of the software.

6.2 Any direct or indirect losses, legal disputes, equipment damage, data loss, game account penalties, or other risks suffered by users due to obtaining or using this software, regardless of the cause, shall be borne entirely by the users themselves, and the operator/developer team shall not be held liable.

6.3 The operator/developer team assumes no obligation to supervise, guarantee, mediate, or compensate for users' usage behavior. All issues arising from the use of this software are unrelated to this project and the developer team.

6.4 Any behavior by users that violates the usage restrictions of this agreement and laws and regulations constitutes a breach of contract. Users shall independently bear all civil, administrative, and even criminal liabilities arising therefrom, and compensate for all losses caused to the operator/developer team or other third parties.

### 7. Agreement Effectiveness and Final Interpretation
The act of downloading, installing, or using this software by users constitutes complete understanding and irrevocable consent to all terms of this agreement. The final interpretation rights of all terms of this agreement and the operational management rights of the software belong to the developer team. The developer team has the right to unilaterally change the content of this agreement or terminate the service when necessary, without prior individual notification to users.

----------------------------------------------------------------------------------------------

# Features | Function

## Intelligent Path Selection

![image](doc/select.png)

## Precise Target Locking

![image](doc/battle.png)

## Iron Warrior
![image](doc/iron_blood.png)

## Currency War

A standalone Currency War module that automatically collects the compendium entries for investment strategies, investment environments, opening affixes, and more.

## Finger Snap (In Testing)
![image](doc/finger_snap.png)

## Advanced Features

### Video Recording

In the name of love, she treasures everything that has passed away... until the end of time
![image](doc/end.png)
At least, such an ending is gentle enough

### Early Reincarnation

If this world cannot bring salvation, then bring it destruction... (if 40 kills are achieved, which is extremely unlikely, restart immediately)
![image](doc/retry.png)

## Map Frequency Analysis

Corresponds to `user/backup/map_visits.db`, with the two columns ['map_id', 'visit_count'].
```cmd
python -c "import sqlite3; print('\n'.join(map(str, sqlite3.connect('user/backup/map_visits.db').execute('SELECT * FROM map_visits ORDER BY visit_count DESC;'))))"
```

## Node Log Query

Corresponds to `user/backup/node_log.db`, with the three columns ['id', 'created_at', 'data'].
```cmd
python -c "import sqlite3; print('\n'.join(map(str, sqlite3.connect('user/backup/node_log.db').execute(\"SELECT id, created_at, json_extract(data, '$.area') AS area, json_extract(data, '$.event') AS event, json_extract(data, '$.plane_floor') AS plane_floor FROM node_log ORDER BY id DESC;\"))))"
```

## Event Log Query (emergency)

Corresponds to `user/backup/emergency.db`, with the three columns ['id', 'created_at', 'data'].
```cmd
python -c "import sqlite3; print('\n'.join(map(str, sqlite3.connect('user/backup/emergency.db').execute(\"SELECT id, created_at, json_extract(data, '$.count') AS count, json_extract(data, '$.node_count') AS node_count, json_extract(data, '$.event') AS event, json_extract(data, '$.plane_floor') AS plane_floor FROM node_log ORDER BY id DESC;\"))))"
```

## Uninstall

Simply delete the entire folder
![image](doc/delete.png)
Then... walk towards tomorrow


----------------------------------------------------------------------------------------------

## Compatibility

Only supports 1920x1080 and above screens, with HDR disabled.
The game resolution must be 1920x1080 (windowed or fullscreen), and the render quality must be at least 1.0
Set the text language to Simplified Chinese. The game window must not be obstructed and must stay in the foreground.

Due to the onnxruntime environment, please ensure Windows 10 is version 2004 or later (Windows 11 is supported by default). More than 2 GB of VRAM is recommended.

The download and extraction directory must not contain Chinese characters in its path!!

# Download | Download

**Method 1: Download the packaged build (recommended)**

- QQ group files / Simulated Scepter program & key / SimSce-v1.x.x.zip
  - ![](https://img.shields.io/badge/QQ%201群-1072802257-4e4c97)
![](https://img.shields.io/badge/QQ%202群-870863632-4e4c97)
  - This is the in-group release (stable version). It is relatively stable and has fewer bugs, but it does not include the latest features and bug fixes.
- GitHub: [Release](https://github.com/syfoud/Simulated_Scepter/releases), latest release - Assets - SimSce-v1.x.x.zip
  - This is the latest packaged test build. It is updated frequently, is relatively unstable, and has more bugs. It includes the latest updates, whose details can be found on the same page.


**Method 2: Download the source code and deploy locally**

If you have no experience with Python or Git, ignore the tutorial below and download the resources from the community group instead.

1. First, git clone this project, or Download Zip and extract it.
2. Open the program folder, select the address bar at the top, type cmd and press Enter.
3. (Skip this step if uv is already installed.) Run the following three commands in order to install uv:
```cmd
powershell -ExecutionPolicy ByPass -c "iex (iwr -useb https://astral.sh/uv/install.ps1)"
set Path=%USERPROFILE%\.local\bin;%Path%
uv sync
```
4. Run the following command to start the program (`uv run` normally installs missing dependencies automatically, i.e. `uv sync`).
```cmd
uv run new_gui.py
```
5. To start the program again later, repeat steps 2 and 4.


**Run a task automatically on startup**

You can pass arguments to run the engine and script from the configuration when the program starts, together with a wait time.
```powershell
uv run new_gui.py --start-task --engine:ironblood --file:insect.json --start-delay:10
```

The engine (`--engine:`), script (`--file:`) and delay (`--start-delay:`) arguments are all optional. Without the engine and script options, the values in the settings file are used; without the delay option, the program waits 5 seconds by default. Option names must be lowercase, while engine IDs and script names are case-insensitive.

The default engine is `IronBlood` and the default script is `core/any_fate/actions/insect.json` (engine IDs and script names are case-insensitive, and a bare file name is also accepted). If the startup arguments are invalid, a dialog reminds you; the program still opens normally but does not run a task this time.

**Rust-accelerated node graph analysis for Finger Snap**

Install the Rust stable toolchain first, then run:

```plaintext
uv run python scripts/build_countdown_native.py
```

Run it once on first deployment or after modifying the Rust source; official builds compile and bundle the dynamic library automatically.

----------------------------------------------------------------------------------------------

# Configuration Recommendations

Engines are organized under `core/<module>/`; the run entry point and the gear settings window are discovered dynamically through `module.ini`. Each module keeps its own code, configuration and UI, so new settings do not require changes to the main window. See [Engine modules and standalone settings UI](docs/development/内核配置界面.md) for the directory layout, inheritance and legacy configuration migration.

- Slot 1: characters that can instantly kill small enemies, such as Phainon, Acheron and Silver Wolf LV.999 (Himeko • Nova is not supported yet), or ranged characters.
- Slot 2: characters with a high success rate at catching Warp Trotters, such as Topaz and Silver Wolf LV.999.
- Other slots: any character. Characters that increase Technique Points (Phainon, Himeko • Nova) and a sustain slot that heals at the start of the battle (for example Dan Heng • Permansor Terrae with the "We Are Wildfire" Light Cone) are recommended.

### Calibration

Sometimes the view angle may rotate too much or too little, causing navigation issues. You can try manual calibration:

Enter the game, teleport your character to Herta's Office, then click the calibration angle button in the GUI, and wait for the view rotation/spinning in place to complete.

Changing mouse DPI may affect the calibration value, requiring recalibration at that time.

**Note: Do not move the game window after starting the run/calibration, otherwise the script may perform actions incorrectly. To move it, press end to stop the automation first.**

## GUI Usage

**First Run**

Adjust your system settings. In the game, enable "Apply Battle Settings Automatically", and select your team characters in the Destruction lineup on the Swarm Disaster screen.

**Run the Scepter**

Click "Promote Iron Warrior" to run.

**Run Currency War**

On the "Currency War Settings" page, select the exit plane and save, then click "Currency War Auto Collection" to run.

----------------------------------------------------------------------------------------------

# Development Chat - Player Community - Aid Destruction | Destruction
- Contains stable releases of this Scepter system.
- ![](https://img.shields.io/badge/QQ%201群-1072802257-4e4c97)
![](https://img.shields.io/badge/QQ%202群-870863632-4e4c97)

----------------------------------------------------------------------------------------------

# Support Development | Star or Buy Coffee

### Give a Star - If you find this project helpful, please give it a free Star in the upper right corner. Thank you!

### WeChat Donation

<img alt="image" height="300" src="doc/pay.jpg" width="300"/>


# Acknowledgements

This project uses the following excellent open-source libraries and tools:

## Core Dependencies

- **[OpenCV](https://opencv.org/)** - Image processing and computer vision library, used for image recognition, template matching, and minimap analysis
- **[NumPy](https://numpy.org/)** - Scientific computing library, providing efficient array operations and numerical computation support (OpenCV dependency)
- **[Pillow](https://python-pillow.org/)** - Python image processing library, used for image loading and processing
- **[PyAutoGUI](https://pyautogui.readthedocs.io/)** - Automation control library, implementing simulated mouse and keyboard operations
- **[pywin32](https://github.com/mhammond/pywin32)** - Windows API interface, used for window management and system-level operations
- **[keyboard](https://github.com/boppreh/keyboard)** - Global keyboard listening and control library

## OCR and Deep Learning

- **[ONNX Runtime](https://onnxruntime.ai/)** - Cross-platform machine learning inference engine, supporting DirectML acceleration, used for PaddleOCR model inference

## GUI Framework

- **[PyQt5](https://www.riverbankcomputing.com/software/pyqt/)** - Python bindings for the Qt framework, building graphical user interfaces

## Data Processing and Configuration

- **[Shapely](https://shapely.readthedocs.io/)** - Geometric object manipulation library, used for spatial analysis and path planning
- **[pyclipper](https://github.com/greginvm/pyclipper)** - Polygon clipping library, used in conjunction with OCR
- **[SciPy](https://scipy.org/)** - Scientific computing library, used for signal processing and minimap analysis
- **[Matplotlib](https://matplotlib.org/)** - Data visualization library, used for debugging and data analysis (development/testing dependency)
- **[ipykernel](https://ipython.org/)** - Jupyter kernel support (development/testing dependency)

## Related Open Source Projects
- **[Auto_Simulated_Universe](https://github.com/CHNZYX/Auto_Simulated_Universe/)** - Core foundation of this project, significantly refactored based on this project
- **[StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot/)** - Inspiration for advanced state machine architecture, high-precision map positioning

## Special Thanks
### Contributors

Thanks to the following contributors for their contributions to this project:

<a>

  <img src="https://contrib.rocks/image?repo=syfoud/Simulated_Scepter" />

</a>

### All Sponsors

Your support is the driving force behind the author's development and maintenance of this project!

### And every user who starred this project:
[![Star History](https://star-history.dera.page/svg?repos=syfoud/Simulated_Scepter&type=Date)](https://star-history.dera.page/#syfoud/Simulated_Scepter&Date)
