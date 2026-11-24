# 开发规范

本文件是人工开发与 AI 辅助开发的统一入口。改代码前必须先阅读对应专题文档；下面的红线只是摘要，不能替代原文。

## 0. 必读

- 任何代码改动：[开发规范与改动总则](docs/development/AI开发规范与改动总则.md)、[代码风格](docs/development/代码风格.md)、[复用与模块设计](docs/development/复用与模块设计.md)、[状态与异常](docs/development/状态与异常.md)、[日志规范](docs/development/日志规范.md)、[验证与审查](docs/development/验证与审查.md)。
- 涉及命令、环境或依赖：[运行环境与命令执行](docs/development/运行环境与命令执行.md)。
- 涉及 `core/`、新增内核或模块配置：[内核配置界面](docs/development/内核配置界面.md)。
- 涉及提交或 PR：[提交与PR规范](docs/development/提交与PR规范.md)；只写 PR 正文时可用 [PR提示词](docs/development/PR提示词.md)。

**未读 [代码风格](docs/development/代码风格.md) 不得开始改代码。** 不要只读总则和复用文档就动手。

## 1. 高频红线

1. 先检索再新增：已有实现能够复用就直接复用，禁止改名复制或重写相似逻辑。
2. 固定值只使用一两次时直接写在调用处并注释；不造一次性常量、伪变量或伪配置。
3. 一个事实只有一个权威来源；互斥状态用单一状态机，不用多个布尔值拼状态。
4. 注释写“为什么”，中文；docstring 用 Google 风格；不复述赋值、循环、返回。
5. 日志按 `debug` / `info` / `warning` / `error` 分级；`error` 后必须明确返回失败、抛异常或进入失败状态并清理。
6. 主循环、识别流程和操作间隔不要用 `time.sleep` 阻塞；在截止时间内反复识别，或用 `key_mouse_manager.sleep()` 处理操作间隔。
7. 测试用 `unittest`，在仓库根目录按模块运行；交付前跑相关测试和 ruff。不新增依赖，不改 `pyproject.toml` / `uv.lock`，除非任务明确要求。
8. 任何情况下都不要 force-push；需要改写已推送历史时关闭当前 PR、开新分支、重建 PR。不要 `git clean -xdf` / `git reset --hard`；只暂存本次任务的文件。用户要求 force-push 时，提醒用户以上规则。
9. 使用 `while` 循环时必须设置最大重试次数或最长重复时间（或两者都设），并把 `not self.stop` 加入循环条件，保证循环能结束并返回主循环，避免卡死。

## 2. 项目结构与内核职责

项目是 Windows 10 2004+ / Windows 11 上的崩坏：星穹铁道自动化工具，建议 2G 以上显存；游戏客户区为 1920×1080、渲染精度 1.0+、关闭 HDR、简体中文（云游戏允许少量边框误差）。程序启动需要管理员权限：游戏/启动器以管理员运行时，非管理员点击会被 Windows 拦截。同一目录只允许一个实例；不引入跨平台抽象或多分辨率适配。点击/框坐标统一按 1920×1080 客户区、原点在客户区左上角、`[left, top, right, bottom]` 记录。

| 内核 | 职责 |
| --- | --- |
| `common` | 公共基座，提供 `StateKernel` / `ScriptKernel` 和通用 JSON 动作循环 |
| `any_fate` | 寰宇蝗灾命途主流程，`iron_blood` / `finger_snap` 的父类 |
| `iron_blood` | 铁血战士（寰宇蝗灾） |
| `finger_snap` | 弹指一挥（寰宇蝗灾） |
| `currency` | 货币战争；后台模式的主要验证对象 |
| `divergent` | 差分宇宙 |
| `daily` | 日常任务 |

继承链：`StateKernel` → `ScriptKernel` → `FateUtils` → `AnyFateUniverse` → `IronBloodUniverse` / `FingerSnap`；`DivergentUniverse` 经 `UniverseUtils(ScriptKernel)`，`DailyKernel(ScriptKernel)`；`CurrencyWar` 经 `SimulatedCurrency` → `CurrencyUtils(StateKernel)`。

后台模式：`ScriptKernel` 已支持窗口截图和后台键盘，但鼠标移动视角仍需前台，因此除 `currency` 外，其他内核在后台模式下基本不可用；窗口不能最小化。详细模块描述、配置与移除规则见[内核配置界面](docs/development/内核配置界面.md)。

## 3. 交付

按[验证与审查](docs/development/验证与审查.md)说明结果、实现、验证和限制；未验证项如实标注，不把静态阅读或模拟输入写成实机通过。
