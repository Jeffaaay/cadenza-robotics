"""Plot existing FE displacement fields, not a fracture or motion animation.

Input: J6_ABC-h2.8-bend_Z_0.5kg.npz produced by fea.py --fields at E=1670.
The second panel uses exact E rescaling at fixed nu and load, not an
orthotropic PET-CF constitutive model. No geometry is redesigned.
"""
import argparse
from pathlib import Path
import hashlib
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--field',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parent
field=np.load(args.field)
points=field['points']; faces=field['faces']; u=field['displacement']
assert args.field.name=='J6_ABC-h2.8-bend_Z_0.5kg.npz'
baseline=json.loads((root/'results/J6-rigid-h2.8.json').read_text())
case=next(c for c in baseline['cases'] if c['case']=='bend_Z_0.5kg')
assert abs(np.linalg.norm(u,axis=1).max()/case['max_displacement_mm']-1)<.05
plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
plt.rcParams['axes.unicode_minus']=False
fig=plt.figure(figsize=(12.8,7),facecolor='white')
fig.text(.04,.94,'同一份 J6 CAD：受力后，模型中的薄板会弯',fontsize=22,weight='bold',color='#1e324c')
fig.text(.04,.885,'灰色：原形状    橙色：线弹性变形外形    蓝色：固定端    位移显示 ×1（未额外放大）',fontsize=12,color='#4c607b')
for i,(E,title) in enumerate([(1670,'PLA 参数'),(4730,'PET-CF 的 XY 模量参数')]):
    scale=1670/E
    ax=fig.add_axes([.035+i*.49,.22,.46,.52],projection='3d')
    base=Poly3DCollection(points[faces],facecolors='#7b8797',edgecolors='none',alpha=.13)
    deform=Poly3DCollection((points+u*scale)[faces],facecolors='#e39136',edgecolors='none',alpha=.7)
    ax.add_collection3d(base);ax.add_collection3d(deform)
    fixed=np.unique(field['fixed_facets'])
    ax.scatter(*points[fixed].T,s=1,color='#2464b4',depthshade=False)
    for dimension,limits in zip('xyz',[(-85,45),(-45,45),(-60,35)]):
        getattr(ax,'set_'+dimension+'lim')(limits)
    ax.view_init(elev=20,azim=-65)
    ax.set_box_aspect((130,90,95));ax.set_axis_off()
    value=case['reference_displacement_norm_mm']*scale
    fig.text(.265+i*.49,.775,f'{title} · E={E} MPa\n此方向接口平移指标 {value:.2f} mm',fontsize=15,ha='center')
fig.text(.04,.19,'工况：原水平伸臂载荷＋500 g 物品，J6 的 Z 向弯曲包络；两图的 CAD、载荷和固定方式相同。',fontsize=11,color='#334962')
fig.text(.04,.135,'这是求解场的展示，不是实物下垂量预测：线弹性模型未描述大变形、开裂、层间剥离或螺栓滑动。',fontsize=11,color='#b34c35')
fig.text(.04,.08,'右图只换一个刚度参数，并不代表 PET-CF 打印方向已经建模；完整材料比较还缺各向异性、热态和真实接头。',fontsize=10,color='#53647a')
fig.text(.04,.035,'来源：2026-11-19 J6 FE 场；2026-11-20 同 CAD 模量敏感性可视化。两图均不能作为生产验收。',fontsize=10,color='#53647a')
fig.savefig(root/'same-cad-deformation.png',dpi=150)
plt.close(fig)
(root/'same-cad-deformation-source.json').write_text(json.dumps({
 'field_name':args.field.name,'field_sha256':hashlib.sha256(args.field.read_bytes()).hexdigest(),
 'base_result':'results/J6-rigid-h2.8.json','base_result_sha256':hashlib.sha256((root/'results/J6-rigid-h2.8.json').read_bytes()).hexdigest(),
 'case':case['case'],'E_proxies_MPa':[1670,4730],'displacement_display_multiplier':1,
 'note':'Second field is E-scaled at fixed nu; neither field is a nonlinear/fracture prediction.'
},indent=2)+'\n',encoding='utf-8',newline='\n')
print(root/'same-cad-deformation.png')
