from pathlib import Path
import argparse, json, hashlib
import numpy as np
import mujoco
parser=argparse.ArgumentParser(description='Static gravity review; requires the complete MuJoCo model and its assets.')
parser.add_argument('--model',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
SRC=args.model
args.output_dir.mkdir(parents=True,exist_ok=True)
m=mujoco.MjModel.from_xml_path(str(SRC));d=mujoco.MjData(m)
name=lambda typ,s:mujoco.mj_name2id(m,typ,s)
ids=[i for i in range(m.nbody) if (mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,i) or '').startswith('openarm_right_')]
records=[]
for label,angles in [('下垂',[0]*7),('屈肘示例',[0.7,0,0,1.1,0,0,0]),('水平前伸',[np.pi/2,0,0,0,0,0,0])]:
    d.qpos[:]=0;d.qvel[:]=0
    for side,sign in [('right',1),('left',-1)]:
        a=list(angles);a[0]*=sign
        for j,q in enumerate(a,1):
            jid=name(mujoco.mjtObj.mjOBJ_JOINT,f'openarm_{side}_joint{j}')
            assert m.jnt_range[jid,0]<=q<=m.jnt_range[jid,1]
            d.qpos[m.jnt_qposadr[jid]]=q
    mujoco.mj_forward(m,d)
    bid=name(mujoco.mjtObj.mjOBJ_BODY,'openarm_right_ee_base_link')
    point=d.xpos[bid]+d.xmat[bid].reshape(3,3)@np.array([0,0,-.1])
    base=name(mujoco.mjtObj.mjOBJ_BODY,'openarm_right_base_link')
    moment=sum((np.cross(d.xipos[i]-d.xpos[base],np.array([0,0,-9.81*m.body_mass[i]])) for i in ids),start=np.zeros(3))
    jac=np.zeros((3,m.nv));jacr=np.zeros((3,m.nv));mujoco.mj_jac(m,d,jac,jacr,point,bid)
    torques=[]
    for j in range(1,8):
        jid=name(mujoco.mjtObj.mjOBJ_JOINT,f'openarm_right_joint{j}');a=m.jnt_dofadr[jid]
        torques.append({'j':j,'gravity_empty_Nm':float(d.qfrc_bias[a]),'extra_per_kg_Nm':float(9.81*jac[2,a])})
    expected=np.zeros(m.nv)
    for i in ids:
        cj=np.zeros((3,m.nv));cr=np.zeros((3,m.nv))
        mujoco.mj_jacBodyCom(m,d,cj,cr,i)
        expected+=9.81*m.body_mass[i]*cj[2]
    right_dofs=[m.jnt_dofadr[name(mujoco.mjtObj.mjOBJ_JOINT,f'openarm_right_joint{j}')] for j in range(1,8)]
    err=float(np.max(np.abs(expected[right_dofs]-d.qfrc_bias[right_dofs])))
    assert err<1e-9,err
    records.append({'pose':label,'q_right_rad':angles,'object_point_world_m':point.tolist(),'object_point_assumption':'EE body local [0,0,-0.100] m, not a measured grasp point','self_weight_base_moment_Nm':moment.tolist(),'joints':torques,'gravity_jacobian_crosscheck_max_error_Nm':err})
mass={mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,i):float(m.body_mass[i]) for i in ids}
result={'source':'v2/'+SRC.name,'source_url':'https://github.com/enactic/openarm_mujoco/blob/a3c8a57ec15d385e3c1dbd3fd090ee486b7f258c/v2/openarm_bimanual.xml','sha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'mujoco_version':mujoco.__version__,'scope':'Local model inertials; not measured hardware. Forward kinematics and static gravity only; no motion rollout, collisions or strength certification.','body_masses_kg':mass,'single_arm_including_base_and_gripper_kg':sum(mass.values()),'poses':records}
(args.output_dir/'load-calculation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('Computed three poses; static gravity cross-check passed.')
