"""Repository entry point. Hardware actions require explicit user commands."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys
import xml.etree.ElementTree as ET

REPO=Path(__file__).resolve().parents[1]
FPGA=REPO/'outputs/parallel_baseband/competition_project_route_opt'
UI=REPO/'deliverables/ui_professional/measurement_console_route_opt'

def environment():
    tmp=REPO/'tmp';tmp.mkdir(exist_ok=True)
    env=dict(os.environ,BASEBAND_PYTHON=sys.executable,BASEBAND_PROJECT_500=str(FPGA),
             BASEBAND_TEMP=str(tmp),TEMP=str(tmp),TMP=str(tmp),TMPDIR=str(tmp),
             PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    env['PYTHONPYCACHEPREFIX']=str(tmp/'pycache')
    return env

def check():
    identity=json.loads((REPO/'release_identity.json').read_text(encoding='utf-8'))
    for name,expected in identity['hardware_files'].items():
        assert hashlib.sha256((FPGA/name).read_bytes()).hexdigest()==expected, name
    sys.path.insert(0,str(FPGA/'host'))
    from live_transport import verify_firmware
    manifest=verify_firmware()
    files=json.loads((REPO/'SHA256SUMS.json').read_text(encoding='utf-8'))
    for name,expected in files.items():
        assert hashlib.sha256((REPO/name).read_bytes()).hexdigest()==expected,name
    check_xpr()
    print(f'PASS: {len(files)} repository files; {len(manifest["hashes"])} firmware/runtime files; hardware identity matches')

def check_xpr():
    project=REPO/'vivado/parallel.xpr'
    tree=ET.parse(project).getroot()
    part=tree.find("./Configuration/Option[@Name='Part']")
    assert part is not None and part.get('Val')=='xc7z020clg400-1'
    top=tree.find("./FileSets/FileSet[@Name='sources_1']/Config/Option[@Name='TopModule']")
    assert top is not None and top.get('Val')=='competition_top'
    macros={'$PPRDIR':project.parent,'$PSRCDIR':project.parent/'parallel.srcs'}
    inputs=[]
    for item in tree.iter('File'):
        name=item.get('Path','')
        resolved=None
        for macro,folder in macros.items():
            if name.startswith(macro+'/'):
                resolved=(folder/name[len(macro)+1:]).resolve()
                break
        assert resolved is not None, 'Unexpected XPR reference: '+name
        assert resolved.is_relative_to(REPO.resolve()),'External XPR reference: '+name
        assert resolved.is_file(),'Missing XPR input: '+name
        inputs.append(resolved)
    rtl=list((FPGA/'rtl').glob('*.v'))+list((FPGA/'rtl').glob('*.mem'))
    assert set(p.resolve() for p in rtl).issubset(set(inputs)), 'RTL or initialization data missing from XPR'
    expected=json.loads((FPGA/'results/build_source_hashes.json').read_text(encoding='utf-8'))['hashes']
    for name in ('fft_lane','competition_axi','competition_vio','competition_ila'):
        ip=project.parent/f'parallel.srcs/sources_1/ip/{name}/{name}.xci'
        key=f'../../../work/route_opt_build/parallel.srcs/sources_1/ip/{name}/{name}.xci'
        assert hashlib.sha256(ip.read_bytes()).hexdigest()==expected[key], 'Archived IP identity mismatch: '+name
        config=json.loads(ip.read_text(encoding='utf-8'))['ip_inst']
        generated=(ip.parent/config['gen_directory']).resolve()
        assert generated.is_relative_to(project.parent.resolve()),'External IP output directory: '+name
    print(f'PASS: portable XPR; {len(inputs)} source/constraint/IP references; 4 archived IP identities match')

def prepare():
    workspace=REPO/'work/rebuild'
    target=workspace/'outputs/parallel_baseband/competition_project_route_opt'
    if target.exists():
        raise RuntimeError('work/rebuild already exists. Use the existing project, or move that folder before preparing another build.')
    for folder in ('rtl','ip_seed','scripts','tb','vectors','host','docs'):
        shutil.copytree(FPGA/folder,target/folder)
    (target/'results').mkdir()
    (workspace/'work').mkdir()
    print('Prepared isolated source:',target)
    return target

def vivado(value):
    sys.path.insert(0,str(UI))
    from vivado_locator import find_vivado
    return find_vivado(value)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['check','ui','prepare','create','build','simulate'])
    parser.add_argument('--vivado',default='')
    args=parser.parse_args()
    env=environment();os.environ.update(env)
    if args.command=='check':check();return
    if args.command=='ui':
        check()
        command=[sys.executable,'-X','utf8','-B',str(UI/'run_console.py'),'--version','500']
        if args.vivado:command+=['--vivado',args.vivado]
        raise SystemExit(subprocess.call(command,cwd=REPO,env=env))
    if args.command=='prepare':prepare();return
    executable=vivado(args.vivado)
    version=subprocess.run([executable,'-version'],capture_output=True,text=True,errors='replace',env=env)
    if '2025.2' not in version.stdout+version.stderr:
        raise RuntimeError('Rebuild/simulation requires Vivado 2025.2 (original FFT IP version); current executable is '+executable)
    target=REPO/'work/rebuild/outputs/parallel_baseband/competition_project_route_opt'
    if not target.exists():target=prepare()
    script={'create':'create_project.tcl','build':'build.tcl','simulate':'simulate.tcl'}[args.command]
    project=REPO/'work/rebuild/work/route_opt_build/parallel.xpr'
    if args.command in ('build','simulate') and not project.is_file():
        raise RuntimeError('Run create first to generate the project and IP')
    logs=REPO/'work/logs';logs.mkdir(parents=True,exist_ok=True)
    command=[executable,'-mode','batch','-source',str(target/'scripts'/script),
             '-log',str(logs/(args.command+'.log')),'-journal',str(logs/(args.command+'.jou'))]
    raise SystemExit(subprocess.call(command,cwd=logs,env=env))

if __name__=='__main__':main()
