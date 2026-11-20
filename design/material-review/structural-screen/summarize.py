"""Validate saved elasticity results and render their measured numerical evidence."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--results', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
font = Path('C:/Windows/Fonts/msyh.ttc')
if font.exists():
    font_manager.fontManager.addfont(str(font))
    plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(font)).get_name()
plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False,
                     'figure.facecolor': '#f4f6f9', 'axes.facecolor': '#ffffff', 'axes.unicode_minus': False})

names = [('J1', '肩根 J1_A'), ('J4', '肘部 J4_A'), ('J6', '前臂 J6_A/B/C'), ('box', '闭合箱形概念（3 mm 壁厚）')]
summary = {'scope': 'Linear elastic component screening; no hardware or full PLA assembly validation.', 'parts': {}}
for prefix, label in names:
    candidates = sorted(args.results.glob(f'{prefix}-rigid-h*.json'))
    runs = [json.loads(p.read_text()) for p in candidates]
    runs.sort(key=lambda r: r['mesh_hmax_mm'], reverse=True)
    if not runs:
        continue
    fine = runs[-1]
    convergence = None
    if len(runs) >= 2:
        coarse = runs[-2]
        changes = [abs(a['reference_displacement_norm_mm']-b['reference_displacement_norm_mm'])/
                   b['reference_displacement_norm_mm'] for a, b in zip(coarse['cases'], fine['cases'])]
        convergence = max(changes)
    for run in runs:
        assert run['volume_relative_error'] < .01
        for case in run['cases']:
            assert case['relative_free_residual'] < 1e-6
            assert case['relative_reaction_force_error'] < 1e-5
            assert case['relative_reaction_moment_error'] < 1e-5
    if convergence is not None:
        assert convergence < .05, (prefix, convergence)
    summary['parts'][prefix] = {'label': label, 'finest_h_mm': fine['mesh_hmax_mm'],
        'mesh_refinement_max_relative_displacement_change': convergence,
        'solid_equivalent_PLA_mass_g': fine['cad_volume_mm3']*.00131,
        'dofs': fine['dofs'], 'volume_relative_error': fine['volume_relative_error'], 'cases': fine['cases']}

beam = json.loads((args.results/'beam-rigid-h4.json').read_text())
analytical = 100**3/(3*1670*(10*10**3/12))
measured = beam['cases'][0]['reference_displacement_norm_mm']
summary['beam_validation'] = {'Euler_Bernoulli_mm': analytical, 'FEA_mm': measured,
    'relative_error': abs(measured-analytical)/analytical}
assert summary['beam_validation']['relative_error'] < .03

for part in summary['parts'].values():
    at_half = [c for c in part['cases'] if c['payload_kg'] == .5]
    part['half_kg_screen'] = {'max_reference_displacement_mm': max(c['reference_displacement_norm_mm'] for c in at_half),
        'max_rotation_deg': max(np.linalg.norm(c['rotation_rad'])*180/np.pi for c in at_half),
        'max_principal_tension_MPa': max(c['max_principal_tension_MPa'] for c in at_half)}
    part['homogeneous_E_sensitivity'] = {str(e): part['half_kg_screen']['max_reference_displacement_mm']*1670/e
                                        for e in [1000, 1670, 1960]}

(args.out/'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')

fig, axes = plt.subplots(2, 2, figsize=(13.5, 9))
for ax, (prefix, label) in zip(axes.flat, names):
    p = summary['parts'].get(prefix)
    if not p:
        ax.set_visible(False)
        continue
    orientations = list(dict.fromkeys(c['case'].rsplit('_', 1)[0] for c in p['cases']))
    for i, direction in enumerate(orientations):
        cases = [c for c in p['cases'] if c['case'].startswith(direction+'_')]
        ax.plot([c['payload_kg'] for c in cases], [c['reference_displacement_norm_mm'] for c in cases],
                'o-', lw=2.3, color=['#2477b3', '#d06a32'][i], label=direction)
    ax.axhline(1, color='#b43b45', ls='--', lw=1, label='暂定部件目标 1 mm')
    status_label = {'J1': '位移小；孔边应力 / 连接待核', 'J4': '原尺寸换材未过筛查',
                    'J6': '原尺寸换材未过筛查', 'box': '理想截面；未含电机安装接口'}[prefix]
    ax.set_title(label+'\n'+status_label, loc='left', fontweight='bold', fontsize=11)
    ax.set_xlabel('每臂物品质量（kg）')
    ax.set_ylabel('参考接口线弹性位移（mm）')
    ax.set_xticks([0, .25, .5])
    ax.set_yscale('log')
    ax.grid(True, alpha=.18)
    ax.legend(fontsize=8)
fig.suptitle('OpenArm · PLA 机械筛查\n原金属外形与闭合截面概念，同一材料与载荷假设', x=.07, ha='left', fontsize=18, fontweight='bold')
fig.text(.07, .02, 'E = 1,670 MPa；原模型惯量；两向载荷包络。大位移结果仅表明线弹性筛查失效，不代表实际下垂距离。\n箱形概念未含电机安装、轴承孔、开口、螺栓和分件接头，不能据此打印装机。', fontsize=10, color='#455063')
fig.tight_layout(rect=(.02,.08,.99,.89), h_pad=2)
fig.savefig(args.out/'screening-results.png', dpi=170)
plt.close(fig)

fig = plt.figure(figsize=(14, 6.4))
selections = [('J4', 'J4_A', 'bend_X'), ('J6', 'J6_ABC', 'bend_Y'), ('box', 'box_3', 'bend_Y')]
for index, (prefix, partname, direction) in enumerate(selections, 1):
    p = summary['parts'].get(prefix)
    if not p:
        continue
    file = args.results/f"{partname}-h{p['finest_h_mm']}-{direction}_0.5kg.npz"
    if not file.exists():
        continue
    d = np.load(file)
    xyz, triangles = d['points'], d['faces']
    ax = fig.add_subplot(1, 3, index, projection='3d', computed_zorder=False)
    displacement = np.linalg.norm(d['displacement'], axis=1)
    face_u = displacement[triangles].mean(axis=1)
    cmap = plt.cm.viridis
    norm = plt.Normalize(0, displacement.max())
    collection = Poly3DCollection(xyz[triangles], facecolors=cmap(norm(face_u)), linewidths=0, rasterized=True)
    ax.add_collection3d(collection)
    for key, color in [('fixed_facets', '#2588ec'), ('loaded_facets', '#ed5648')]:
        markers = xyz[np.unique(d[key])]
        ax.scatter(*markers.T, s=6, color=color, depthshade=False, zorder=10)
    lo, hi = xyz.min(axis=0), xyz.max(axis=0)
    for setlim, a, b in zip([ax.set_xlim,ax.set_ylim,ax.set_zlim], lo,hi):
        setlim(a-3,b+3)
    ax.set_box_aspect(hi-lo)
    ax.view_init(elev=22, azim=-58 if prefix == 'J4' else -55)
    ax.set_xlabel('X (mm)', fontsize=8)
    ax.set_ylabel('Y (mm)', fontsize=8)
    ax.set_zlabel('Z', fontsize=8)
    for axis in [ax.xaxis, ax.yaxis, ax.zaxis]:
        axis.set_major_locator(plt.MaxNLocator(4))
    ax.tick_params(labelsize=7)
    case = next(c for c in p['cases'] if c['case'] == f'{direction}_0.5kg')
    ax.set_title(f"{partname} · {direction}\n接口位移指标 {case['reference_displacement_norm_mm']:.3f} mm", fontsize=12)
    sm = plt.cm.ScalarMappable(cmap=cmap,norm=norm)
    fig.colorbar(sm,ax=ax,shrink=.52,pad=.08,label='线弹性位移指标（mm）')
fig.suptitle('实际网格与边界条件 · 原几何形状显示，未放大变形', fontsize=17, fontweight='bold', y=.98)
fig.text(.08,.04,'蓝色：理想固定面 / 孔；红色：6 自由度刚性加载接口。颜色表示 0.5 kg 包络工况的线弹性位移幅值。\n各图色标独立；结果超出小变形或材料范围时，只用于拒绝筛查，不作为真实位移或断裂位置预测。',fontsize=10,color='#455063')
fig.subplots_adjust(left=.015,right=.98,bottom=.18,top=.82,wspace=.16)
fig.savefig(args.out/'mesh-and-boundaries.png',dpi=170)
plt.close(fig)
print(json.dumps({k:v['half_kg_screen'] for k,v in summary['parts'].items()},ensure_ascii=False,indent=2))
