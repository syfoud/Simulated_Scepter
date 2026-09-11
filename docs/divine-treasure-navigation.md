# 神赐珍宝局内寻路：重构设计（待主人确认）

更新时间：2026-09-11。分支：`divine-treasure-navigation`。

## 第一版判断是错的（留档防复犯）

曾误判 `diver.py: DivergentUniverse` 为差分宇宙寻路。**事实：差分宇宙没有小地图**；`take_fine_minimap`/`exist_minimap` 是模拟宇宙 `UniverseUtils` 的死代码，`diver.py` 根本不调用。模拟宇宙 ≠ 差分宇宙是红线。

## 差分宇宙寻路现状（出处）

- 参考实现：主 checkout（Wanderland-dev，**未提交 WIP，禁止碰**）的 `wanderland.py: WanderlandUniverse(DivergentUniverse)`，2142 行；连带 `tool/wanderland/{door_detector,settings,strategy}.py`。
- 检测层：`tool/wanderland/door_detector.py` 用 March7th 同源 YOLO（`divergent.onnx`，本地未跟踪）+ 粉色随意门模板 `door.png`；UI 模板在 `resource/imgs/wanderland/`（21 张，本地未跟踪）。
- 现有实现的问题（用户实测：找不到怪、冲过头、流程正常但不点门）：`wanderland.py: process_battle_stage()` 是**开环控制**——`keyDown("w")`+`sleep(2.0)` 盲走，再朝屏幕中央 [960,540] 盲打，3 轮不成即判定"无怪"转找门；全程不检测怪物位置。

## 重构设计

1. **保留**：输入原语（`tool/diver/keyops.py`，master 已跟踪）、Ocr/按键/坐标封装、UI 模板匹配思路。
2. **废弃**：固定时长盲走 + 居中盲打 + 无限探索。
3. **新结构**：`tool/divine_treasure/navigation.py`，纯状态机 + 依赖注入：
   - `NavIO`：`capture() / forward(t) / turn(dx) / attack() / interact()`，实机注入真实输入，测试注入回放帧；
   - `NavObservation`：`enemy / door / battle_hud / stage_icon`，由可注入检测器产出（等主人精准截图后接线）；
   - 每个状态都有**超时与 tick 上限**，任何失败都返回结果而不是挂住。
4. **可测试性**：离线回放夹具（现有 logs/wanderland_*.png + 主人下一轮精准截图），无游戏即可回归"不卡死"。
5. **资源路径可配置**：模板/模型不进 commit（本地未跟踪），缺失时降级为纯状态推进，不静默漏检。

## 待主人提供

- 精准截图：战斗区（怪/顶部敌标记/战斗 HUD）、粉色随意门与交互提示（F 图标）、事件区与区域标题。
- 下一轮据此接线检测层并做有界实机探针。
