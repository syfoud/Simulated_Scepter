# 神赐珍宝局内寻路：开发准备

更新时间：2026-09-11。分支：`divine-treasure-navigation`（自 `divine-treasure` @ 874dd74 拉出）。

## 分支策略（为什么这样拉）

- 新开发从 `divine-treasure` 拉出，PR #130 的提交天然是共同历史；等 #130 合并进 master 后，最后的总 PR 只显示新增工作量，不掺重复提交。
- `divine-treasure-navigation` 待 `divine-treasure` 合并后按需同步（必要时用 `git merge -s ours divine-treasure` 标记已合并，保持 diff 干净）。
- PR #130 现状：OPEN、已取消草稿、CI（lint + startup）全绿、无冲突；**只差一次他人 Approve**——GitHub 禁止作者自批，且仓库未开启 auto-merge，当前账号只有 write 权限。

## 关键发现：差分宇宙的局内能力已经存在

`diver.py` 的 `DivergentUniverse(UniverseUtils)`（1164 行）与 `tool/diver/utils.py` 的 `UniverseUtils`（1719 行）构成一套**独立的差分宇宙技术栈**（与旧模拟宇宙的 `simul.py` / `iron_blood.py` 是两套代码）：

| 能力 | 位置 |
| --- | --- |
| 局内主循环（等窗口 → OCR → 分派动作） | `diver.py: route()` / `loop()` |
| 区域状态机（识别区域、进出、楼层） | `diver.py: area()` / `get_now_area()` / `init_floor()` |
| 行进（按 W + 转视角 + 文本判定） | `diver.py: forward_until()` / `aim_portal()` / `portal_bias()` |
| 小地图与终点定位 | `tool/diver/utils.py: get_end_point()` / `exist_minimap()` / `take_fine_minimap()` / `get_bw_map()` |
| 输入原语 | `tool/diver/keyops.py`（`KeyController`）+ `UniverseUtils.press/sprint/click/drag` |
| 战斗、事件、祝福、队伍识别 | `diver.py: skill()` / `event()` / `bless()` / `find_team_member()` |

**因此「局内寻路」大概率不需要从零实现**：先确认复用范围，再决定写多少代码。

## 现有神赐珍宝入口的边界

`divine_treasure_entry.py` 是轻量 OCR + 点击流程（协议 5 → 面具页），`divine_treasure_masks.py` 走到"首个战斗区域"即停，**不含任何局内移动**；文档亦声明不复用旧模拟宇宙的 UI/导航/模式逻辑（此约束针对 `simul.py` / `iron_blood.py`，不涉及差分宇宙技术栈）。

## 待确认（决定实现量）

1. 局内寻路要覆盖到哪：只做"区域内走到下一个节点/交互点"，还是连区域决策、战斗、事件一起？
2. 复用方式：(A) 在 `DivergentUniverse` 上加神赐珍宝策略层；(B) 把入场接到 `DivergentUniverse` 主循环；(C) 只用底层移动/识别能力自建轻量循环。
3. 实机验证授权与观察点：建议先做一个有界实机探针（`forward_until` 只走一段、有超时、有前后截图、F8 可停），验证小地图/移动方向/坐标基准是否可靠。

## 下一步（建议）

1. 主人确认范围与复用方式。
2. 按现有纪律：先补模拟测试，再做有界实机探针，每次都有超时与证据目录。
3. 涉及实机前确认游戏停在对应页面；`logs/` 已被忽略，证据可安全落盘。
