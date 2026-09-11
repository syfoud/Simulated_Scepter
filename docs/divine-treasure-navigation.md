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

## 实测判据（battle-sample1/2 与实机日志）

| 判据 | 方法 | 实测数值 | 结论 |
| --- | --- | --- | --- |
| 顶部 Z 图标（`enemy.png`） | 模板匹配顶部 12% 带 | 贴近 1.000；清怪后 0.501、门口 0.517、祝福页 0.539 | 可靠：**固定位置**，只表示"附近有怪" |
| 怪物红点 | 暗红低亮（H≈5-16, S≈255, V≈48-86）+ 中部带 | 近距帧有、远处与清怪后无 | 用于判断"已进入攻击距离" |
| 战斗界面 | 顶部 OCR 标签（行动中/自动战斗/战斗中） | 沿用 wanderland.py 既有实现 | 主判据 |
| 战斗界面（兜底） | 底部中央橙色占比 | 大世界 0.80-0.97，战斗 0.27，菜单页 0.0006 | `0.05 <= ratio < 0.80` 判为战斗 |
| 祝福页 | 顶部中带暗色占比 | 0.794（大世界 0.075-0.107） | 阈值 0.5 区分 |
| 粉色随意门 | 粉色大块 + 高度 + 填充度 | 真门最小块 20153px / 高占比 0.22；误检最大 4955px / 0.14 | 交互文字只在门口出现，必须靠颜色找门 |
| 怪物红圈（大） | 暗红阈值 + 形状 | 与角色红发连成同一连通域 | **不可靠，不参与判定** |

## 现行状态机（tool/divine_treasure/navigation.py）

```
find_enemy   角色初始朝向怪物 → 持续前进直到 Z 图标出现；若门已在画面则直接找门
approach     红点出现（进入攻击距离）才平A；否则碎步靠近
verify       平A 后等 2 秒后摇：Z 图标消失或出现战斗界面 = 命中；仍在 = 空挥 → 碎步重试（连续 8 次放弃）
battle       等 Z 图标消失且回到大世界
after_battle 有门就按 F 过门；出现祝福页转 blessing
blessing     点击中间祝福卡 + 右下确认，最多 10 轮后转 find_door
find_door    粉色门定位后按 F
```

全程由 `budget`（默认 300 秒）与 `max_ticks` 双上限兜底，到期返回 `timeout`。

## 待做

- 实机校验：红点判据、空挥重试步长、祝福卡与确认按钮坐标（2026-09-12 实测）。
- 面具等级小界面：首次启动检查一次是否展开（未展开则 Alt + 点击展开图标），之后只识别。
- 事件区/其他区域类型的寻路（当前只覆盖战斗区）。
