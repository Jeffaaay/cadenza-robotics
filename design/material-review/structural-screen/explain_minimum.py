"""Render a plain-language view of existing component results; no new FEA.

Run from any directory. Inputs are the committed summary.json (2026-11-19).
The cross sections are explanatory sketches, not CAD or manufacturing drawings.
"""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'summary.json').read_text(encoding='utf-8'))
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def interval(part, load):
    values = [c['reference_displacement_norm_mm']
              for c in DATA['parts'][part]['cases'] if c['payload_kg'] == load]
    assert len(values) == 2
    return min(values), max(values)

def formatted(part, load, digits):
    lo, hi = interval(part, load)
    return f'{lo:.{digits}f}–{hi:.{digits}f} mm'

fig = plt.figure(figsize=(13.5, 8), facecolor='#f6f8fc')
fig.text(.055, .935, '同样是 PLA：形状，比“填满一点”更关键', fontsize=23,
         weight='bold', color='#16273d')
fig.text(.055, .885, '已有 J6 前臂部件筛查 · 两个载荷方向的读数范围 · 不是全臂仿真',
         fontsize=13, color='#53647a')

for x, kind, title, color in [(.055, 'J6', '原薄板外形直接换 PLA', '#c75d40'),
                             (.535, 'box', '改成理想闭合箱体，仍用 PLA', '#167e85')]:
    ax = fig.add_axes([x, .28, .41, .55])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor='white', edgecolor='#dce3ee', lw=1.4))
    ax.text(.06, .91, title, color=color, weight='bold', fontsize=17)
    if kind == 'J6':
        for sx in [.32, .65]:
            ax.add_patch(Rectangle((sx, .56), .025, .22, facecolor=color))
        ax.text(.5, .48, '薄板构思示意', ha='center', fontsize=11, color='#657187')
    else:
        ax.add_patch(Rectangle((.32, .56), .36, .22, facecolor=color))
        ax.add_patch(Rectangle((.35, .59), .30, .16, facecolor='white'))
        ax.text(.5, .48, '封闭截面示意', ha='center', fontsize=11, color='#657187')
    for y, load, label in [(.35, 0, '空手'), (.23, .5, '拿 500 g')]:
        ax.text(.07, y, label, fontsize=14, color='#394b63')
        ax.text(.93, y, formatted(kind, load, 1 if kind == 'J6' else 3),
                ha='right', fontsize=20, weight='bold', color=color)
    note = ('已触发刚度失败；大位移不能当作真实下垂量'
            if kind == 'J6' else '没有电机孔、轴承孔或真实接缝，尚不能装机')
    ax.text(.5, .07, note, ha='center', fontsize=10, color='#53647a')

fig.text(.055, .205,
         f'J4 上臂薄框架更差：空手筛查读数 {formatted("J4", 0, 1)}，原外形直接打印不可采用。',
         fontsize=13, color='#a83d35', weight='bold')
fig.text(.055, .15,
         '读数是部件加载接口平移，不是夹爪末端误差。空手仍承受手臂和电机自重。',
         fontsize=12, color='#394b63')
fig.text(.055, .105,
         '线弹性、均匀材料 E=1670 MPa；原模型惯量；理想夹紧。大位移/高应力已超出物理预测适用范围。',
         fontsize=10, color='#53647a')
fig.text(.055, .067,
         '闭合箱体较原 J6 用料更多（约 111 g vs 19 g），也缺真实开口；结果支持重设计，不构成强度或寿命验收。',
         fontsize=10, color='#53647a')
fig.text(.055, .027,
         '来源：2026-11-19 component screening / summary.json · 本图仅重绘既有结果 · 截面示意不按比例',
         fontsize=9, color='#7b8799')
fig.savefig(ROOT / 'minimum-explained.png', dpi=150, facecolor=fig.get_facecolor())
plt.close(fig)
print(ROOT / 'minimum-explained.png')
