"""Same CAD / fixed load / fixed nu elastic-modulus sensitivity.

This is an exact rescaling of the stated isotropic linear FE model, NOT an
orthotropic material simulation or a metal-print manufacturing qualification.
One fresh J4 solve at E=4730 MPa independently checks the scaling numerically.
"""
from pathlib import Path
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parent
SOURCES = {
    'PLA Matte': 'https://store.bblcdn.com/s7/default/5b061f2feeac4ba88f355a33248bbda7/Bambu_PLA_Matte_Technical_Data_Sheet.pdf',
    'PET-CF': 'https://store.bblcdn.eu/s8/default/df83cdd0401b4c169d7883a3e7bd2c8a/Bambu_PET-CF_Technical_Data_Sheet.pdf',
    'PAHT-CF': 'https://store.bblcdn.eu/s8/default/91dea87af3414d878a0696d2c51b98f7/Bambu_PAHT-CF_Technical_Data_Sheet_V2.pdf',
    'Printed 316L reference': 'https://www.tpc.toray/en/technology/additive-print/add_material/add_material_001.html',
}
MATERIALS = [
    ('PLA Matte', 'Z', 1670), ('PLA Matte', 'XY', 1960),
    ('PET-CF', 'Z', 2160), ('PET-CF', 'XY', 4730),
    ('PAHT-CF', 'Z', 2180), ('PAHT-CF', 'XY', 3860),
    ('Printed 316L reference', 'Z', 180000),
    ('Printed 316L reference', 'XY', 185000),
]
FILES = {'J1_A':'J1-rigid-h4.json', 'J4_A':'J4-rigid-h2.8.json',
         'J6_ABC':'J6-rigid-h2.8.json'}

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
baseline = {part:json.loads((ROOT/'results'/file).read_text()) for part,file in FILES.items()}
fresh_path = ROOT/'results/J4-rigid-h2.8-E4730.json'
fresh = json.loads(fresh_path.read_text())
ref = baseline['J4_A']
assert fresh['E_MPa'] == 4730 and ref['E_MPa'] == 1670
assert fresh['poisson_assumed'] == ref['poisson_assumed'] == .35
for key in ['tetrahedra','dofs','fixed_boundary_triangles','loaded_boundary_triangles']:
    assert ref[key] == fresh[key], key
errors=[]
for original,rerun in zip(ref['cases'],fresh['cases']):
    assert original['case']==rerun['case']
    assert original['force_N']==rerun['force_N'] and original['moment_Nmm']==rerun['moment_Nmm']
    predicted=original['reference_displacement_norm_mm']*1670/4730
    errors.append(abs(rerun['reference_displacement_norm_mm']/predicted-1))
assert max(errors)<1e-5

records=[]
for part,data in baseline.items():
    for name,direction,modulus in MATERIALS:
        cases=[]
        for case in data['cases']:
            scale=data['E_MPa']/modulus
            translation=case['reference_displacement_norm_mm']*scale
            rotation=math.degrees(math.sqrt(sum(x*x for x in case['rotation_rad'])))*scale
            cases.append({
                'case':case['case'], 'payload_kg':case['payload_kg'],
                'force_N':case['force_N'], 'moment_Nmm':case['moment_Nmm'],
                'interface_translation_mm':translation,
                'interface_rotation_deg':rotation,
                'translation_screen_1mm':translation<=1,
                'rotation_screen_0_5deg':rotation<=.5,
            })
        records.append({'part':part,'material_parameter_source':name,
                        'datasheet_test_direction':direction,
                        'isotropic_E_proxy_MPa':modulus,'assumed_nu':.35,'cases':cases})

result={
 'date':'2026-11-20',
 'scope':'Same unmodified CAD, original fixed loads, nu=0.35; scalar isotropic E sensitivity only. No redesigned box included.',
 'method':'K scales with E at fixed nu. u(E)=u(1670)*1670/E. Directional TDS moduli are separate isotropic proxies, not physical orientation predictions or rigorous bounds.',
 'limitations':[
  'Retains original assembly inertials; not an all-plastic or all-316L reweighted assembly.',
  'No full orthotropic stiffness tensor, layer paths, voids, interfaces, creep, thermal softening, nonlinear deformation, fracture or buckling.',
  'Large displacement/high stress results are rejection indicators beyond the small-strain model validity, not actual sag distances.',
  'The arbitrary engineering translation/rotation screens are not task-derived tolerances or a load rating.',
  'Strength is NOT passed here. At fixed force, same nu and uniform E, this model stress field is unchanged by E alone; material-specific allowables are required.',
  'The 316L comparison uses supplier reference elastic moduli only; no manufacturing process, fit, density substitution or whole-arm qualification.',
  'Only J1_A, J4_A and J6_A/B/C assessed, not every part. TDS specimen processing differs from an arbitrary P1S print.',
 ],
 'sources':SOURCES,
 'baseline_files':{key:{'path':'results/'+file,'sha256':digest(ROOT/'results'/file)} for key,file in FILES.items()},
 'geometry_sha256':{f.name:digest(f) for f in sorted((ROOT/'geometry').glob('*.step'))},
 'loads_sha256':digest(ROOT/'load-cases.json'),
 'independent_rerun':{'path':'results/'+fresh_path.name,'sha256':digest(fresh_path),
                     'max_relative_translation_difference_vs_scaling':max(errors),
                     'number_of_load_cases':len(errors),'elapsed_seconds':fresh['elapsed_seconds']},
 'records':records,
}
(ROOT/'same-cad-materials.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print('Independent J4 rerun/scaling maximum relative difference:',max(errors))
for name,direction,E in MATERIALS:
    if (name=='PLA Matte' and direction=='Z') or (name!='PLA Matte' and direction=='XY'):
        row=[]
        for part in FILES:
            item=next(r for r in records if r['part']==part and r['material_parameter_source']==name and r['datasheet_test_direction']==direction)
            cases=[c for c in item['cases'] if c['payload_kg']==.5]
            row.append(round(max(c['interface_translation_mm'] for c in cases),4))
        print(name,direction,E,row)
