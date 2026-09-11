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

## 实测判据（battle-sample1/2，2026-09-11）

| 判据 | 方法 | 实测数值 | 结论 |
| --- | --- | --- | --- |
| 顶部敌标记 | `enemy.png` 模板匹配顶部 12% 带 | 贴近时 1.000；清怪后 0.501、门口 0.517、祝福页 0.539 | 可靠：贴标记表示区域仍有敌人 |
| 战斗界面 | 底部中央橙色占比 | 大世界 0.80-0.97，战斗界面 0.27，祝福页 0.0006 | 可靠：`0.05 <= ratio < 0.80` 判为战斗 |
| 粉色随意门 | 粉色大块 + 填充度 | 门口帧与背对门帧均能定位，误差 < 20% 屏宽 | 可靠（交互文字只在门口出现，故必须靠颜色找门） |
| 怪物红圈 | 暗红阈值 + 形状 | 与角色红发连成同一连通域（清怪后帧暗红像素更多） | **不可靠，不参与判定** |

模型在远处（初始帧）不渲染敌标记，模板分只有 0.508，因此"有标记"只在贴近后成立；寻路因此按"敌标记存在 → 靠近 → 战斗界面跳变"闭环推进。

## 状态机（tool/divine_treasure/navigation.py）

`find_enemy`（转视角搜索，上限 6 次）→ `approach`（对准 + 前进 + 平A，以战斗界面跳变确认进战斗）→ `in_battle`（等结束）→ `blessing`（可连续多轮）→ `find_door`（转视角找粉色门）→ `interact`。

任何阶段都由 `budget`（默认 60 秒）与 `max_ticks` 双上限兜底，到期返回 `timeout`，不会挂住。

## 待做

- 实机有界探针：`--run --stage battle`（待主人确认页面后执行，F8 可停）。
- 面具等级小界面：首次启动检查一次是否展开（未展开则 Alt + 点击展开图标），之后只识别不操作。
- 事件区/其他区域类型的寻路（当前只覆盖战斗区）。
