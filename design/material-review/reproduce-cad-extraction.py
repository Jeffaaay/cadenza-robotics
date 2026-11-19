from pathlib import Path
import argparse, json, hashlib, re
import numpy as np
from build123d import import_step, GeomType

parser=argparse.ArgumentParser(description='Extract upstream STEP geometry; does not design PLA replacements.')
parser.add_argument('--step',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
SRC=args.step
OUT=args.output_dir
OUT.mkdir(parents=True,exist_ok=True)
root=import_step(SRC)
parts=[]
def walk(node,parent=''):
    label=str(node.label)
    if node.children:
        for c in node.children: walk(c,parent+'/'+label)
        return
    if '_mir' in parent: return
    if not (re.match(r'^J[1-7]_\w|^J[1-7]-|^end-efector_|^camera_mount|^cable_holder|^DM|^FL|^MR|^B680|^GEA|^MSGS|^SETS|^HFS|^base_plate|^chest_cover|^HBL|^HFBL',label)): return
    b=node.bounding_box()
    vs,fs=node.tessellate(0.5,0.22)
    v=np.array([list(x) for x in vs])
    tf=(node.global_location*node.location.inverse()).wrapped.Transformation()
    rotation=np.array([[tf.Value(i,j) for j in range(1,4)] for i in range(1,4)])
    translation=np.array([tf.Value(i,4) for i in range(1,4)])
    v=v@rotation.T+translation
    v=v[:,[0,2,1]];v[:,1]*=-1
    circles=[]
    if label in ['J1_A','J1_B','J1_C','J4_B','J4_C','J7_B','J7_C']:
        for e in node.edges():
            if e.geom_type==GeomType.CIRCLE:
                c=e.geom_adaptor().Circle();p=c.Location()
                circles.append({'r':round(c.Radius(),4),'p':[round(p.X(),3),round(p.Y(),3),round(p.Z(),3)]})
    parts.append({'name':label,'parent':parent,'size_mm':list(b.size),'source_min_mm':list(b.min),'source_max_mm':list(b.max),'volume_mm3':node.volume,'circles':circles,'v':np.round(v,3).tolist(),'f':fs})
walk(root)
(OUT/'cad-meshes.json').write_text(json.dumps(parts,separators=(',',':')),encoding='utf-8')
index=[{k:v for k,v in x.items() if k not in ['v','f']} for x in parts]
(OUT/'cad-part-index.json').write_text(json.dumps({'source':'OpenArm 2.0/'+SRC.name,'source_url':'https://github.com/enactic/openarm_hardware/releases/tag/2.0.0','sha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'units':'mm','coordinate_note':'Index bounds/circles use leaf local placement; mesh vertices include ancestor transforms and Y-up to Z-up rotation.','parts':index},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'parts':len(parts),'triangles':sum(len(x['f']) for x in parts),'source_sha256':hashlib.sha256(SRC.read_bytes()).hexdigest()}))
