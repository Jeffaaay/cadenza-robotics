import argparse
import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
m = mujoco.MjModel.from_xml_path(str(args.model.resolve()))
d = mujoco.MjData(m)
name = lambda kind, value: mujoco.mj_name2id(m, kind, value)
joint_ids = [name(mujoco.mjtObj.mjOBJ_JOINT, f'openarm_right_joint{i}') for i in range(1, 8)]

def descendants(root):
    found = []
    for body in range(1, m.nbody):
        test = body
        while test and test != root:
            test = m.body_parentid[test]
        if test == root:
            found.append(body)
    return found

records = []
poses = {'down': [0] * 7, 'horizontal': [np.pi/2, 0, 0, 0, 0, 0, 0],
         'bent': [0.7, 0, 0, 1.1, 0, 0, 0]}
for pose, q in poses.items():
    for side, sign in [('right', 1), ('left', -1)]:
        for i, angle in enumerate(q, 1):
            joint = name(mujoco.mjtObj.mjOBJ_JOINT, f'openarm_{side}_joint{i}')
            d.qpos[m.jnt_qposadr[joint]] = angle * (sign if i == 1 else 1)
    mujoco.mj_forward(m, d)
    ee = name(mujoco.mjtObj.mjOBJ_BODY, 'openarm_right_ee_base_link')
    object_point = d.xpos[ee] + d.xmat[ee].reshape(3, 3) @ [0, 0, -.1]
    for payload in [0, .25, .5]:
        for section, body_name in [('shoulder', 'openarm_right_link1'),
                                   ('elbow', 'openarm_right_link4'),
                                   ('wrist', 'openarm_right_link6')]:
            body = name(mujoco.mjtObj.mjOBJ_BODY, body_name)
            children = descendants(body)
            reference = d.xpos[body]
            forces = [np.array([0, 0, -9.81*m.body_mass[b]]) for b in children]
            force = sum(forces, start=np.zeros(3)) + [0, 0, -9.81*payload]
            moment = sum((np.cross(d.xipos[b]-reference, f) for b, f in zip(children, forces)), start=np.zeros(3))
            moment += np.cross(object_point-reference, [0, 0, -9.81*payload])
            records.append({'pose': pose, 'q_right_rad': q, 'payload_kg': payload, 'section': section,
                'downstream_mass_kg': float(sum(m.body_mass[children])),
                'reference_world_m': reference.tolist(), 'force_world_N': force.tolist(),
                'moment_world_Nm': moment.tolist(), 'force_norm_N': float(np.linalg.norm(force)),
                'moment_norm_Nm': float(np.linalg.norm(moment))})

collisions = []
for frame in range(121):
    phase = frame/120
    d.qpos[:] = 0
    for side, sign in [('right', 1), ('left', -1)]:
        values = [sign*phase*np.pi/2, .15*np.sin(np.pi*phase), 0, .7*np.sin(np.pi*phase), 0, 0, 0]
        for i, angle in enumerate(values, 1):
            joint = name(mujoco.mjtObj.mjOBJ_JOINT, f'openarm_{side}_joint{i}')
            assert m.jnt_range[joint, 0] <= angle <= m.jnt_range[joint, 1]
            d.qpos[m.jnt_qposadr[joint]] = angle
    mujoco.mj_forward(m, d)
    for contact in d.contact:
        if contact.dist < -.001:
            bodies = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[g]) for g in [contact.geom1, contact.geom2]]
            collisions.append({'frame': frame, 'penetration_m': float(-contact.dist), 'bodies': bodies})

output = {'model_sha256': hashlib.sha256(args.model.read_bytes()).hexdigest(), 'mujoco_version': mujoco.__version__,
          'scope': 'Original rigid-body inertials retained, including motors. Static load extraction plus 121 sampled configurations; no material stiffness, dynamics, controller or redesigned clearance validation.',
          'object_point': 'EE body local [0,0,-0.1] m; assumed, not measured', 'sections': records,
          'motion_screen': {'frames': 121, 'penetrations_over_1mm': collisions}}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_bytes(json.dumps(output, indent=2).encode())
for item in records:
    if item['pose'] == 'horizontal':
        print(item['section'], item['payload_kg'], 'F', round(item['force_norm_N'], 3), 'M', round(item['moment_norm_Nm'], 3))
print('Configuration contacts over 1mm:', len(collisions))
