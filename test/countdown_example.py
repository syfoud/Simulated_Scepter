"""
单图推演接口示例 — 修改下方参数后直接运行。
用法: python test/countdown_example.py
"""
import os, sys
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'test'))

from test_countdown_optimizer import analyze_single_map
from countdown_map_loader import default_map_paths

# ============================================================
# ↓↓↓ 修改以下参数 ↓↓↓
# ============================================================

# 方式A: 传入图像路径
IMAGE_PATH = default_map_paths()[0]

# 方式B: 传入预构建图（与 IMAGE_PATH 互斥，设为 None 则用方式A）
NODES = None        # [{'idx': 7, 'name': 'trade', 'cx': 100}, ...]
EDGES = None        # {7: [1, 6], 1: [5], ...}
START_IDX = None    # 7
INFECTABLE = None   # set()

# 图像匹配参数
MATCH_MODE = 1      # 识别失败时会自动回退另一套节点模板
PLANE = 1           # 位面 1/2/3

# 资源 & 训练参数
CHEAT = 2
REROLL = 3
INITIAL_CD = 15         # 进入该地图时的初始 CD
TARGET_CD = 20          # 目标 CD（计算胜率），不需要填 None
OBSERVED_EFFECT = None     # 1~6 观察到的效果（仅 locked/settled 时有效）
EFFECT_STATE = "unlocked"    # unlocked=效果未出现(事前评估) | locked=已观察可决策 | settled=已结算
# 效果编号: {1: '浇灌', 2: '为善', 3: '对症', 4: '慈怀', 5: '归心', 6: '可憎'}
N_TRAIN = 10000         # 当前精确状态控制 rollouts
N_EVAL = 10000          # 六种效果下所有候选动作的独立选择预算
N_SIM_TRIALS = 10000    # 已选条件策略的最终事前评价预算

# ============================================================
# ↑↑↑ 修改以上参数 ↑↑↑
# ============================================================

if __name__ == '__main__':
    if NODES is not None and EDGES is not None and START_IDX is not None and INFECTABLE is not None:
        result = analyze_single_map(
            nodes=NODES, edges=EDGES,
            start_idx=START_IDX, infectable=INFECTABLE,
            cheat=CHEAT, reroll=REROLL,
            initial_countdown=INITIAL_CD,
            observed_effect=OBSERVED_EFFECT,
            effect_state=EFFECT_STATE,
            target_cd=TARGET_CD,
            n_train=N_TRAIN, n_eval=N_EVAL, n_sim_trials=N_SIM_TRIALS,
            plane=PLANE,
        )
    else:
        result = analyze_single_map(
            image_path=IMAGE_PATH,
            cheat=CHEAT, reroll=REROLL,
            initial_countdown=INITIAL_CD,
            observed_effect=OBSERVED_EFFECT,
            effect_state=EFFECT_STATE,
            target_cd=TARGET_CD,
            n_train=N_TRAIN, n_eval=N_EVAL, n_sim_trials=N_SIM_TRIALS,
            match_mode=MATCH_MODE,
            plane=PLANE,
        )

