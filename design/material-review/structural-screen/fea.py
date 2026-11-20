"""Small-strain 3-D elasticity screening, in N, mm and MPa."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import gmsh
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu
from skfem import MeshTet, Basis, FacetBasis, ElementVector, ElementTetP2, LinearForm, asm
from skfem.helpers import dot
from skfem.models.elasticity import linear_elasticity, lame_parameters


def mesh_geometry(name, geometry, h):
    gmsh.initialize()
    gmsh.option.setNumber('General.Terminal', 0)
    gmsh.model.add(name)
    if name == 'beam_check':
        gmsh.model.occ.addBox(0, -5, -5, 100, 10, 10)
    elif name.startswith('box_'):
        wall = float(name.split('_')[1])
        outer = gmsh.model.occ.addBox(-75, -32.5, -53, 108.5, 65, 71.6)
        inner = gmsh.model.occ.addBox(-76, -32.5+wall, -53+wall, 110.5, 65-2*wall, 71.6-2*wall)
        gmsh.model.occ.cut([(3, outer)], [(3, inner)])
    elif name == 'J6_ABC':
        for label in ['J6_A', 'J6_B', 'J6_C']:
            gmsh.model.occ.importShapes(str(geometry / f'{label}.step'))
        volumes = gmsh.model.occ.getEntities(3)
        fused, _ = gmsh.model.occ.fuse(volumes[:1], volumes[1:])
        assert len([v for v in fused if v[0] == 3]) == 1
    else:
        gmsh.model.occ.importShapes(str(geometry / f'{name}.step'))
    gmsh.model.occ.synchronize()
    volume = sum(gmsh.model.occ.getMass(3, tag) for _, tag in gmsh.model.getEntities(3))
    gmsh.option.setNumber('Mesh.MeshSizeMax', h)
    gmsh.option.setNumber('Mesh.MeshSizeMin', min(h/3, .6))
    gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 12)
    gmsh.option.setNumber('Mesh.Algorithm3D', 1)
    gmsh.model.mesh.generate(3)
    tags, xyz, _ = gmsh.model.mesh.getNodes()
    _, element_nodes = gmsh.model.mesh.getElementsByType(4)
    order = np.argsort(tags)
    coordinates = np.asarray(xyz).reshape(-1, 3)[order]
    cells = np.searchsorted(np.asarray(tags)[order], element_nodes).reshape(-1, 4)
    gmsh.finalize()
    mesh = MeshTet(coordinates.T, cells.T)
    return mesh, volume


def boundaries(mesh, name):
    boundary = mesh.boundary_facets()
    p = mesh.p[:, mesh.facets[:, boundary]]
    if name == 'beam_check':
        fixed = np.all(p[0] < 1e-6, axis=0)
        loaded = np.all(p[0] > 100-1e-6, axis=0)
        reference = np.array([100., 0, 0])
    elif name.startswith('box_'):
        fixed = np.all(p[0] > 33.5-1e-5, axis=0)
        loaded = np.all(p[0] < -75+1e-5, axis=0)
        reference = np.array([-75., 0, -17.2])
    elif name == 'J6_ABC':
        fixed = np.all(p[0] > 33.5-1e-4, axis=0)
        radial = np.sqrt((p[0]+75)**2+p[1]**2)
        loaded = np.all(np.abs(radial-7.5) < .015, axis=0)
        reference = np.array([-75., 0, -17.2])
    elif name == 'J4_A':
        fixed = np.all(p[1] > 154-1e-4, axis=0)
        loaded = np.zeros(len(boundary), dtype=bool)
        for angle in np.deg2rad([-55, 5, 65, 125, 185, 245]):
            x, y = 25*np.cos(angle), 25*np.sin(angle)
            radial = np.sqrt((p[0]-x)**2+(p[1]-y)**2)
            loaded |= np.all(np.abs(radial-1.7) < .015, axis=0)
        reference = np.array([0., 0, -31.5])
    elif name == 'J1_A':
        fixed = np.zeros(len(boundary), dtype=bool)
        for x in [-52.5, 52.5]:
            for z in [-15, 15]:
                radial = np.sqrt((p[0]-x)**2+(p[2]-z)**2)
                fixed |= np.all(np.abs(radial-3.3) < .015, axis=0)
        loaded = np.all(np.abs(np.sqrt(p[0]**2+p[2]**2)-36) < .015, axis=0)
        reference = np.array([0., 56.5, 0])
    else:
        raise ValueError(name)
    fixed, loaded = boundary[fixed], boundary[loaded]
    if len(fixed) < 4 or len(loaded) < 4 or np.intersect1d(fixed, loaded).size:
        raise ValueError(f'Invalid boundary sets: fixed={len(fixed)}, load={len(loaded)}')
    return fixed, loaded, reference


def wrench_load(basis, facets, reference, force, moment):
    fb = FacetBasis(basis.mesh, basis.elem, facets=facets, intorder=4)
    xyz = np.asarray(fb.global_coordinates())
    area = float(fb.dx.sum())
    center = (xyz*fb.dx).sum(axis=(1, 2))/area
    r = xyz-center[:, None, None]
    inertia = np.eye(3)*np.sum((r*r).sum(axis=0)*fb.dx)-np.einsum('ifq,jfq,fq->ij', r, r, fb.dx)
    about_center = np.asarray(moment)+np.cross(reference-center, force)
    omega = np.linalg.solve(inertia, about_center)

    @LinearForm
    def loading(v, w):
        arm = w.x-center[:, None, None]
        traction = np.asarray(force)[:, None, None]/area + np.cross(omega, arm, axisa=0, axisb=0, axisc=0)
        return dot(v, traction)
    return asm(loading, fb), fb, center, inertia, area


def make_cases(name, data):
    if name == 'beam_check':
        return [{'case': 'tip_1N', 'force_N': [0, 0, 1], 'moment_Nmm': [0, 0, 0]}]
    section = 'elbow' if name == 'J4_A' else 'shoulder' if name == 'J1_A' else 'wrist'
    cases = []
    for record in data['sections']:
        if record['pose'] != 'horizontal' or record['section'] != section:
            continue
        for label, f, moment in (
            [('bend_X', [1, 0, 0], [0, 0, 1]), ('bend_Z', [0, 0, 1], [-1, 0, 0])]
            if name == 'J4_A' else
            [('bend_Y', [0, 1, 0], [0, 0, -1]), ('bend_Z', [0, 0, 1], [0, 1, 0])]
            if name != 'J1_A' else
            [('in_plane', [0, 0, -1], [0, 1, 0]), ('out_of_plane', [0, -1, 0], [1, 0, 0])]
        ):
            cases.append({'case': f"{label}_{record['payload_kg']}kg", 'payload_kg': record['payload_kg'],
                'force_N': (np.array(f)*record['force_norm_N']).tolist(),
                'moment_Nmm': (np.array(moment)*record['moment_norm_Nm']*1000).tolist()})
    return cases


def run(args):
    start = time.perf_counter()
    mesh, cad_volume = mesh_geometry(args.part, args.geometry, args.h)
    fixed, loaded, reference = boundaries(mesh, args.part)
    basis = Basis(mesh, ElementVector(ElementTetP2()), intorder=4)
    dofs_fixed = basis.get_dofs(facets=fixed).all()
    free = basis.complement_dofs(dofs_fixed)
    loaded_dofs = basis.get_dofs(facets=loaded).all()
    interior = np.setdiff1d(free, loaded_dofs)
    node_dofs = np.unique(loaded_dofs//3)
    rows, cols, values = list(interior), list(range(len(interior))), [1.]*len(interior)
    for node in node_dofs:
        x, y, z = basis.doflocs[:, 3*node]-reference
        coupling = np.array([[1,0,0,0,z,-y], [0,1,0,-z,0,x], [0,0,1,y,-x,0]], dtype=float)
        for i, j in zip(*np.nonzero(coupling)):
            rows.append(3*node+i)
            cols.append(len(interior)+j)
            values.append(coupling[i,j])
    transform = coo_matrix((values, (rows, cols)), shape=(basis.N, len(interior)+6)).tocsr()
    lam, mu = lame_parameters(args.E, args.nu)
    print(args.part, 'assembling', mesh.nelements, 'quadratic tetrahedra', flush=True)
    matrix = asm(linear_elasticity(lam, mu), basis)
    print(args.part, 'h', args.h, 'tetrahedra', mesh.nelements, 'DOFs', basis.N, 'factorizing', flush=True)
    reduced = (transform.T@matrix@transform).tocsc()
    factor = splu(reduced)
    print('Factorization ready', flush=True)
    coords = basis.doflocs[:, ::3].T
    assert np.allclose(basis.doflocs[:, ::3], basis.doflocs[:, 1::3])
    data = json.loads(args.loads.read_text())
    cases = make_cases(args.part, data)
    results = []
    for case in cases:
        f, fb, center, inertia, area = wrench_load(basis, loaded, reference, case['force_N'], case['moment_Nmm'])
        force_check = f.reshape(-1, 3).sum(axis=0)
        moment_check = np.cross(coords-reference, f.reshape(-1, 3)).sum(axis=0)
        assert np.linalg.norm(force_check-case['force_N']) < 1e-6
        assert np.linalg.norm(moment_check-case['moment_Nmm']) < 1e-4
        reduced_f = np.zeros(reduced.shape[0])
        reduced_f[-6:] = case['force_N']+case['moment_Nmm']
        assert np.linalg.norm(transform.T@f-reduced_f) < 1e-4
        generalized = factor.solve(reduced_f)
        u = transform@generalized
        residual = matrix@u-f
        residual_error = np.linalg.norm(transform.T@residual)/max(np.linalg.norm(reduced_f), 1e-12)
        reactions = residual.reshape(-1, 3)
        reaction_force_error = np.linalg.norm(reactions.sum(axis=0)+force_check)/max(np.linalg.norm(force_check), 1)
        reaction_moment_error = np.linalg.norm(np.cross(coords-reference, reactions).sum(axis=0)+moment_check)/max(np.linalg.norm(moment_check), 1)
        assert residual_error < 1e-6 and reaction_force_error < 1e-5 and reaction_moment_error < 1e-5
        uf = fb.interpolate(u)
        translation = (np.asarray(uf)*fb.dx).sum(axis=(1, 2))/area
        r = np.asarray(fb.global_coordinates())-center[:, None, None]
        rotation = np.linalg.solve(inertia, (np.cross(r, np.asarray(uf), axisa=0, axisb=0, axisc=0)*fb.dx).sum(axis=(1, 2)))
        reference_displacement = generalized[-6:-3]
        assert np.linalg.norm(rotation-generalized[-3:]) < 1e-8
        gradient = basis.interpolate(u).grad
        strain = .5*(gradient+gradient.swapaxes(0, 1))
        trace = np.einsum('iieq->eq', strain)
        stress = 2*mu*strain+lam*np.eye(3)[:, :, None, None]*trace
        deviator = stress-np.eye(3)[:, :, None, None]*np.einsum('iieq->eq', stress)/3
        von_mises = np.sqrt(1.5*np.einsum('ijeq,ijeq->eq', deviator, deviator))
        principal = np.linalg.eigvalsh(np.moveaxis(stress, (0, 1), (-2, -1)))
        cell_vm = (von_mises*basis.dx).sum(axis=1)/basis.dx.sum(axis=1)
        energy = float(.5*np.dot(u, matrix@u))
        assert energy > 0
        result = {**case, 'reference_displacement_mm': reference_displacement.tolist(),
            'reference_displacement_norm_mm': float(np.linalg.norm(reference_displacement)),
            'rotation_rad': rotation.tolist(), 'max_displacement_mm': float(np.linalg.norm(u.reshape(-1, 3), axis=1).max()),
            'von_mises_max_MPa': float(von_mises.max()), 'max_principal_tension_MPa': float(principal[..., -1].max()),
            'von_mises_cell_mean_p95_MPa': float(np.quantile(cell_vm, .95)),
            'strain_energy_Nmm': energy, 'relative_free_residual': float(residual_error),
            'relative_reaction_force_error': float(reaction_force_error), 'relative_reaction_moment_error': float(reaction_moment_error)}
        results.append(result)
        print(case['case'], 'displacement', round(result['reference_displacement_norm_mm'], 4), 'mm; stress max', round(result['von_mises_max_MPa'], 2), flush=True)
        if args.fields and (case['case'].endswith('0.5kg') or args.part == 'beam_check'):
            prefix = args.out.parent / f"{args.part}-h{args.h}-{case['case']}"
            np.savez_compressed(str(prefix)+'.npz', points=mesh.p.T, cells=mesh.t.T, faces=mesh.facets[:, mesh.boundary_facets()].T,
                displacement=u[basis.nodal_dofs].T, cell_vm_MPa=cell_vm, fixed_facets=mesh.facets[:, fixed].T,
                loaded_facets=mesh.facets[:, loaded].T, reference=reference)
    result = {'part': args.part, 'units': 'N, mm, MPa', 'E_MPa': args.E, 'poisson_assumed': args.nu,
        'element': 'quadratic displacement tetrahedra on straight-sided CAD surface tessellation',
        'mesh_hmax_mm': args.h, 'tetrahedra': int(mesh.nelements), 'dofs': int(basis.N),
        'cad_volume_mm3': cad_volume, 'mesh_volume_mm3': float(basis.dx.sum()),
        'volume_relative_error': float(abs(basis.dx.sum()-cad_volume)/cad_volume),
        'fixed_boundary_triangles': len(fixed), 'loaded_boundary_triangles': len(loaded),
        'reference_mm': reference.tolist(), 'cases': results, 'elapsed_seconds': time.perf_counter()-start,
        'end_interface': 'Rigid six-DOF motor/bearing port coupled to all loaded boundary nodes; exact applied resultant force and moment.',
        'versions': {'gmsh': gmsh.__version__, 'numpy': np.__version__},
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.out.write_bytes(json.dumps(result, indent=2).encode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--part', required=True)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--loads', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--h', type=float, default=4)
    parser.add_argument('--E', type=float, default=1670)
    parser.add_argument('--nu', type=float, default=.35)
    parser.add_argument('--fields', action='store_true')
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run(args)
