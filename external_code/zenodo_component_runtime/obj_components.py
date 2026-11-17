"""OBJ community components: bounded analysis and genuine Blender conversion.

The WebHDP contract adapts the published 0.1.0 processors, replacing their
machine paths and deprecated Blender operations with an isolated file contract.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys

try:
    from .common import staged_file, safe_unpack, sha256, write_json
except ImportError:
    from common import staged_file, safe_unpack, sha256, write_json

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_VERTICES = 5_000_000
MAX_FACES = 5_000_000
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.tga', '.bmp', '.tiff', '.tif', '.webp'}
TEXTURE_KEYS = {'map_kd','map_ka','map_ks','map_ke','map_d','map_bump','bump','disp','decal','norm','map_pr','map_pm','map_ps','refl'}


def boolean_parameters(raw, defaults, extras=()):
    if not isinstance(raw, dict) or set(raw) - set(defaults) - set(extras):
        raise ValueError('Unknown OBJ component parameter.')
    result = dict(defaults)
    for key in defaults:
        if key in raw:
            if type(raw[key]) is not bool:
                raise ValueError(f'{key} must be a boolean.')
            result[key] = raw[key]
    return result


def inside(path, root):
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(root.resolve()):
        raise ValueError('OBJ material and texture references must remain inside the input bundle.')
    return resolved


def reference_path(base, name, root):
    if not name or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Material paths must use portable relative filenames inside the input bundle.')
    return inside(base / name, root)


def texture_name(tokens):
    """Parse common Wavefront texture-map options without mistaking them for paths."""
    fixed = {'-blendu':1,'-blendv':1,'-cc':1,'-clamp':1,'-texres':1,'-bm':1,'-imfchan':1,'-type':1,'-mm':2}
    i = 0
    while i < len(tokens) and tokens[i].startswith('-'):
        flag = tokens[i].lower(); i += 1
        if flag in {'-o','-s','-t'}:
            count = 0
            while i < len(tokens) and count < 3:
                try: float(tokens[i])
                except ValueError: break
                i += 1; count += 1
            if not count: raise ValueError(f'Missing value for material option {flag}.')
        elif flag in fixed:
            i += fixed[flag]
        else:
            raise ValueError(f'Unsupported material texture option {flag}.')
    if i >= len(tokens): raise ValueError('Material texture reference has no filename.')
    return ' '.join(tokens[i:])


def prepare_obj(inputs, output):
    source = staged_file(inputs, 'input_file')
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('OBJ input exceeds 512 MiB.')
    workspace = output / 'source'
    if source.suffix.lower() == '.zip':
        safe_unpack(source, workspace)
        objects = [p for p in workspace.rglob('*') if p.is_file() and p.suffix.lower() == '.obj']
        if len(objects) != 1:
            raise ValueError('The ZIP must contain exactly one OBJ; process scene ZIPs as separate records.')
        obj = objects[0]
    elif source.suffix.lower() == '.obj':
        workspace.mkdir(parents=True, exist_ok=False)
        obj = workspace / source.name
        shutil.copyfile(source, obj)
    else:
        raise ValueError('Supply an OBJ or a ZIP containing one OBJ and its dependencies.')
    dependencies = inputs.get('dependency_files') or []
    if not isinstance(dependencies, list) or len(dependencies) > 1000:
        raise ValueError('dependency_files must be a list of at most 1000 staged files.')
    for value in dependencies:
        dep = staged_file({'dependency':value}, 'dependency')
        target = workspace / dep.name
        if target.exists():
            if sha256(dep) != sha256(target): raise ValueError('Dependency filenames collide; use a ZIP preserving directories.')
        else: shutil.copyfile(dep, target)
    if obj.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('OBJ exceeds 512 MiB after unpacking.')
    return source, obj, workspace


def material_dependencies(obj, root, *, search=False, extensions=IMAGE_SUFFIXES):
    libraries=[]
    for raw in obj.read_text(encoding='utf-8-sig').splitlines():
        tokens=shlex.split(raw, comments=True)
        if tokens and tokens[0]=='mtllib':
            if '\\' in raw: raise ValueError('Material paths must use forward slashes.')
            if len(tokens)<2: raise ValueError('OBJ material library reference has no filename.')
            # Prefer an existing filename containing spaces, otherwise standard multiple libraries.
            combined=' '.join(tokens[1:])
            names=[combined] if (obj.parent/combined).is_file() else tokens[1:]
            for name in names:
                path=reference_path(obj.parent,name,root)
                if path not in libraries: libraries.append(path)
    result={'libraries':[],'textures':[],'materials':[], 'missing':[]}
    for library in libraries:
        rel=library.relative_to(root).as_posix()
        result['libraries'].append({'name':rel,'present':library.is_file()})
        if not library.is_file(): result['missing'].append(rel);continue
        if library.stat().st_size > 16*1024*1024: raise ValueError('MTL exceeds 16 MiB.')
        current_material=''
        for raw in library.read_text(encoding='utf-8-sig').splitlines():
            tokens=shlex.split(raw,comments=True)
            if not tokens:continue
            if tokens[0].lower()=='newmtl':
                current_material=' '.join(tokens[1:]);result['materials'].append(current_material);continue
            if tokens[0].lower() not in TEXTURE_KEYS and not tokens[0].lower().startswith('map_'): continue
            if '\\' in raw: raise ValueError('Material paths must use forward slashes.')
            name=texture_name(tokens[1:]); target=reference_path(library.parent,name,root)
            if not target.is_file() and search:
                matches=[p for p in root.rglob('*') if p.is_file() and p.name.casefold()==Path(name).name.casefold() and p.suffix.lower() in extensions]
                if len(matches)>1: raise ValueError('Texture search is ambiguous; preserve the referenced relative path in the ZIP.')
                if len(matches)==1:
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(matches[0],target)
            present=target.is_file()
            item={'reference':name,'library':rel,'material':current_material,'map':tokens[0].lower(),'present':present}
            if present:
                if target.suffix.lower() not in IMAGE_SUFFIXES: raise ValueError('Material maps must reference supported image files.')
                item['sha256']=sha256(target)
            else:result['missing'].append(target.relative_to(root).as_posix())
            result['textures'].append(item)
    return result


def remove_unresolved_maps(root, dependencies):
    """Do not let Blender's implicit basename/CWD fallback defeat checked resolution.

    Only private staged MTL copies are edited. Missing resources stay explicit in
    the report; permissive conversion exports the material without that map.
    """
    for entry in dependencies['libraries']:
        if not entry['present']:continue
        library=root/entry['name'];kept=[]
        for raw in library.read_text(encoding='utf-8-sig').splitlines(keepends=True):
            tokens=shlex.split(raw,comments=True)
            if tokens and (tokens[0].lower() in TEXTURE_KEYS or tokens[0].lower().startswith('map_')):
                target=reference_path(library.parent,texture_name(tokens[1:]),root)
                if not target.is_file():continue
            kept.append(raw)
        library.write_text(''.join(kept),encoding='utf-8')


def _triangle(a,b,c):
    u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
    cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    area=math.sqrt(sum(x*x for x in cross))/2
    volume=(a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    return area,volume


def triangulate(face, vertices):
    if len(face)==3:return [face]
    # Ear clipping in the dominant projection supports simple concave polygons.
    points=[vertices[i] for i in face]
    normal=[sum((points[i][(axis+1)%3]-points[(i+1)%len(points)][(axis+1)%3])*(points[i][(axis+2)%3]+points[(i+1)%len(points)][(axis+2)%3]) for i in range(len(points))) for axis in range(3)]
    drop=max(range(3),key=lambda i:abs(normal[i]));axes=[i for i in range(3) if i!=drop]
    xy=[(p[axes[0]],p[axes[1]]) for p in points]
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    signed=sum(xy[i][0]*xy[(i+1)%len(xy)][1]-xy[(i+1)%len(xy)][0]*xy[i][1] for i in range(len(xy)))
    if abs(signed)<1e-15:raise ValueError('Cannot triangulate a zero-area polygon.')
    sign=1 if signed>0 else -1;remaining=list(range(len(face)));out=[]
    while len(remaining)>3:
        found=False
        for k,index in enumerate(remaining):
            prev=remaining[k-1];nxt=remaining[(k+1)%len(remaining)]
            if sign*cross(xy[prev],xy[index],xy[nxt])<=1e-15:continue
            if any(all(sign*cross(xy[a],xy[b],xy[j])>=-1e-15 for a,b in ((prev,index),(index,nxt),(nxt,prev))) for j in remaining if j not in (prev,index,nxt)):continue
            out.append([face[prev],face[index],face[nxt]]);remaining.remove(index);found=True;break
        if not found:raise ValueError('OBJ polygon is self-intersecting or cannot be triangulated.')
    out.append([face[i] for i in remaining]);return out


def parse_obj(path, *, detailed=True, quality=False):
    vertices=[];faces=[];counts=Counter();materials=Counter();objects=[];groups=[];active_material=''
    for number,raw in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        counts['total_lines']+=1
        line=raw.split('#',1)[0].strip()
        if not line:
            counts['comment_lines' if raw.lstrip().startswith('#') else 'empty_lines']+=1;continue
        pieces=line.split();kind=pieces[0];values=pieces[1:]
        if kind=='v':
            if len(values)<3:raise ValueError(f'Incomplete OBJ vertex on line {number}.')
            point=list(map(float,values[:3]))
            if not all(math.isfinite(x) for x in point):raise ValueError('OBJ vertices must be finite.')
            vertices.append(point)
            if len(vertices)>MAX_VERTICES:raise ValueError('OBJ vertex limit exceeded.')
        elif kind in {'vt','vn'}:
            coords=list(map(float,values))
            if len(coords)<(3 if kind=='vn' else 1) or not all(math.isfinite(x) for x in coords):raise ValueError(f'Invalid {kind} on line {number}.')
            counts[kind]+=1
        elif kind=='f':
            if len(values)<3 or len(values)>10000:raise ValueError('OBJ faces need 3 to 10000 vertices.')
            face=[]
            for token in values:
                refs=token.split('/')
                if len(refs)>3:raise ValueError('Invalid OBJ face reference.')
                for dimension,index in enumerate(refs):
                    if not index and dimension:continue
                    try:n=int(index)
                    except ValueError as exc:raise ValueError(f'Invalid OBJ index on line {number}.') from exc
                    size=len(vertices) if dimension==0 else counts['vt' if dimension==1 else 'vn']
                    resolved=n-1 if n>0 else size+n
                    if n==0 or not 0<=resolved<size:raise ValueError(f'OBJ index is out of range on line {number}.')
                    if dimension==0:face.append(resolved)
            faces.append(face);materials[active_material]+=1
            if len(faces)>MAX_FACES:raise ValueError('OBJ face limit exceeded.')
        elif kind=='o':objects.append(' '.join(values))
        elif kind=='g':groups.extend(values)
        elif kind=='usemtl':active_material=' '.join(values)
    if not vertices:raise ValueError('OBJ contains no vertices.')
    minimum=[min(p[i] for p in vertices) for i in range(3)];maximum=[max(p[i] for p in vertices) for i in range(3)]
    result={'geometric_vertices':len(vertices),'texture_coordinates':counts['vt'],'vertex_normals':counts['vn'],'faces':len(faces),'objects':len(objects),'groups':len(groups),'object_names':objects,'group_names':groups,'triangle_faces':sum(len(f)==3 for f in faces),'quad_faces':sum(len(f)==4 for f in faces),'n_gon_faces':sum(len(f)>4 for f in faces),'material_names':[m for m in materials if m],'material_usage':dict(materials),'bounding_box':{'min':minimum,'max':maximum,'dimensions':[maximum[i]-minimum[i] for i in range(3)]},'total_lines':counts['total_lines']}
    if detailed or quality:
        triangles=[t for face in faces for t in triangulate(face,vertices)]
        measures=[_triangle(*(vertices[i] for i in t)) for t in triangles]
        edges=Counter(tuple(sorted((face[i],face[(i+1)%len(face)]))) for face in faces for i in range(len(face)))
        directed=Counter((face[i],face[(i+1)%len(face)]) for face in faces for i in range(len(face)))
        closed=bool(faces) and all(n==2 for n in edges.values())
        oriented=closed and all(directed[a,b]==directed[b,a] for a,b in edges)
        result['geometry']={'triangle_count':len(triangles),'surface_area':sum(a for a,_ in measures),'closed_manifold':closed,'consistent_orientation':oriented,'volume':abs(sum(v for _,v in measures)) if oriented else None,'volume_note':'Signed tetrahedral volume for a closed consistently oriented surface.' if oriented else 'Volume withheld: surface is open, non-manifold, or inconsistently oriented.'}
        if quality:result['mesh_quality']={'degenerate_triangles':sum(a<=1e-15 for a,_ in measures),'boundary_edges':sum(n==1 for n in edges.values()),'nonmanifold_edges':sum(n>2 for n in edges.values())}
    return result


def inspect_glb(path):
    data=path.read_bytes()
    if len(data)<20 or struct.unpack_from('<4sII',data)!=(b'glTF',2,len(data)):raise ValueError('Blender did not produce a valid GLB2 container.')
    offset=12;doc=None;binary=None
    while offset<len(data):
        if offset+8>len(data):raise ValueError('Truncated GLB chunk.')
        length,kind=struct.unpack_from('<II',data,offset);offset+=8
        if length%4 or offset+length>len(data):raise ValueError('Invalid GLB chunk length.')
        chunk=data[offset:offset+length];offset+=length
        if kind==0x4e4f534a:doc=json.loads(chunk)
        elif kind==0x004e4942:binary=chunk
    if not isinstance(doc,dict) or not doc.get('meshes'):raise ValueError('Converted GLB contains no meshes.')
    if any(row.get('uri') for row in doc.get('buffers',[])+doc.get('images',[])):raise ValueError('Converted GLB must embed all buffers and textures.')
    accessors=doc.get('accessors',[]);vertices=triangles=0
    for mesh in doc['meshes']:
        for primitive in mesh.get('primitives',[]):
            idx=primitive.get('attributes',{}).get('POSITION')
            if not isinstance(idx,int) or not 0<=idx<len(accessors):raise ValueError('GLB mesh has no POSITION accessor.')
            vertices+=accessors[idx]['count']
            faces=accessors[primitive['indices']]['count'] if 'indices' in primitive else accessors[idx]['count']
            if primitive.get('mode',4)!=4 or faces%3:raise ValueError('Expected triangulated GLB mesh.')
            triangles+=faces//3
    if not vertices or not triangles:raise ValueError('Converted geometry is empty.')
    return {'vertices':vertices,'triangles':triangles,'meshes':len(doc['meshes']),'materials':len(doc.get('materials',[])),'embedded_images':len(doc.get('images',[])),'binary_bytes':len(binary or b'')}


def run(component, inputs, parameters, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if set(inputs)-{'input_file','dependency_files'}:raise ValueError('Unknown OBJ input port.')
    source,obj,root=prepare_obj(inputs,output)
    if component=='obj_statistics_extractor':
        p=boolean_parameters(parameters,{'calculate_detailed_geometry':True,'include_material_analysis':True,'compute_mesh_quality':False})
        stats=parse_obj(obj,detailed=p['calculate_detailed_geometry'],quality=p['compute_mesh_quality'])
        dependencies=material_dependencies(obj,root) if p['include_material_analysis'] else None
        payload={'schema':'webhdp.obj-statistics/1','component':component,'source_sha256':sha256(source),'obj_sha256':sha256(obj),'parameters':p,'results':stats,'dependencies':dependencies,'source_record':'10.5281/zenodo.16993382','implementation':'WebHDP port with validated OBJ indices, concave polygon triangulation and closed-surface volume gate'}
        target=output/'obj-statistics.json';write_json(target,payload)
        return {'report':target},{'vertices':stats['geometric_vertices'],'faces':stats['faces'],'geometry':stats.get('geometry')}
    if component!='obj_to_glb_converter':raise ValueError('Unknown OBJ component.')
    p=boolean_parameters(parameters,{'search_textures':True,'ignore_missing_textures':False,'include_materials':True,'optimize_geometry':False},extras={'texture_search_extensions'})
    extensions=parameters.get('texture_search_extensions','.jpg,.jpeg,.png,.tga,.bmp,.tiff')
    if not isinstance(extensions,str) or len(extensions)>200:raise ValueError('texture_search_extensions must be a bounded comma-separated list.')
    extension_set={x.strip().lower() for x in extensions.split(',') if x.strip()}
    if not extension_set or not extension_set<=IMAGE_SUFFIXES:raise ValueError('Unsupported texture search extension.')
    p['texture_search_extensions']=','.join(sorted(extension_set))
    stats=parse_obj(obj,detailed=False)
    if not stats['faces']:raise ValueError('OBJ conversion requires polygon faces.')
    dependencies=material_dependencies(obj,root,search=p['search_textures'],extensions=extension_set)
    if p['include_materials'] and dependencies['missing'] and not p['ignore_missing_textures']:
        raise ValueError('Missing material/texture dependencies: '+', '.join(dependencies['missing']))
    remove_unresolved_maps(root,dependencies)
    blender=os.environ.get('WEBHDP_BLENDER') or shutil.which('blender')
    if not blender:raise ValueError('The OBJ conversion runtime requires Blender 3.4 or newer.')
    model=output/'converted-model.glb';details=output/'blender-details.json';settings=output/'conversion-settings.json'
    write_json(settings,{'input':str(obj),'output':str(model),'details':str(details),**p})
    log=output/'conversion.log'
    try:
        with log.open('w') as stream:
            subprocess.run([blender,'--background','--factory-startup','--threads','2','--python-exit-code','1','--python',str(Path(__file__).with_name('obj_blender.py').resolve()),'--',str(settings.resolve())],cwd=root,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600)
    except subprocess.CalledProcessError as exc:
        raise ValueError('Blender conversion failed: '+log.read_text(errors='replace')[-4000:]) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Blender conversion exceeded the 600-second limit.') from exc
    geometry=inspect_glb(model)
    warnings=[]
    if p['include_materials'] and any(t['present'] and t['material'] in stats['material_names'] for t in dependencies['textures']) and geometry['embedded_images']==0:
        warnings.append('Used material maps were supplied, but Blender exported no embedded images. Some Wavefront material channels have no glTF equivalent; inspect the converted material before reuse.')
    payload={'schema':'webhdp.obj-conversion/1','component':component,'source_record':'10.5281/zenodo.16995481','implementation':'genuine Blender OBJ import and embedded GLB export','source_sha256':sha256(source),'obj_sha256':sha256(obj),'model_sha256':sha256(model),'parameters':p,'dependencies':dependencies,'input_statistics':stats,'output_geometry':geometry,'blender':json.loads(details.read_text())}
    payload['warnings']=warnings
    report=output/'obj-conversion.json';write_json(report,payload)
    return {'model_file':model,'report':report},geometry
