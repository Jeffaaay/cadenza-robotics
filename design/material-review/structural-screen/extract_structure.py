from pathlib import Path
import argparse
import json
import hashlib
from build123d import import_step, export_step, GeomType, Compound
from OCP.BRepAdaptor import BRepAdaptor_Surface

parser = argparse.ArgumentParser(description='Extract selected OpenArm 2.0 solids in their leaf placement; no assembly-world transforms.')
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
source, out = args.source, args.out
out.mkdir(parents=True, exist_ok=True)
print('Importing STEP assembly', flush=True)
assembly = import_step(source)
records = []

def walk(node, parent=''):
    path = parent + '/' + str(node.label)
    if '_mir' in path:
        return
    if node.children:
        for child in node.children:
            walk(child, path)
        return
    if node.label not in ['J1_A', 'J4_A', 'J4_D', 'J4_E', 'J6_A', 'J6_B', 'J6_C']:
        return
    export_step(Compound(node.wrapped, label=node.label), out / f'{node.label}.step')
    box = node.bounding_box()
    record = {'name': node.label, 'path': path, 'volume_mm3': node.volume,
              'min_mm': list(box.min), 'max_mm': list(box.max), 'faces': []}
    for index, face in enumerate(node.faces()):
        row = {'index': index, 'type': str(face.geom_type), 'area_mm2': face.area,
               'center_mm': list(face.center()), 'bbox_min': list(face.bounding_box().min),
               'bbox_max': list(face.bounding_box().max)}
        if face.geom_type == GeomType.CYLINDER:
            cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
            row['radius_mm'] = cylinder.Radius()
            row['axis'] = list(cylinder.Axis().Direction().Coord())
            row['origin'] = list(cylinder.Location().Coord())
        elif face.geom_type == GeomType.PLANE:
            row['normal'] = list(face.normal_at())
        record['faces'].append(row)
    records.append(record)
    print(node.label, record['min_mm'], record['max_mm'], 'faces', len(record['faces']), flush=True)

walk(assembly)
(out / 'geometry-index.json').write_bytes(json.dumps({'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'coordinates': 'leaf placement within parent; not global assembly coordinates', 'parts': records}, indent=2).encode())
