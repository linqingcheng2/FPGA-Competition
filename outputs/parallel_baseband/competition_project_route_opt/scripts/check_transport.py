"""Reject partial/mixed chunks and preserve exact plot reduction semantics."""
from pathlib import Path
import csv, os, tkinter as tk, hashlib, importlib.util, json, sys, tempfile, time
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from bulk_capture import read_chunk, convert, NAMES

checks = 0
tcl=tk.Tcl();tcl.eval('set ::LIVE_TEST_ONLY 1');tcl.call('source','-encoding','utf-8',str(ROOT/'scripts/live_bridge.tcl'))
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp)/'metrics_ports.csv').write_text('retained hardware record')
    try:tcl.call('live::capture',tmp,8192,0,0,'-',300000,100000,0)
    except tk.TclError as error:assert '避免覆盖' in str(error);checks += 1
    else:raise AssertionError('Existing hardware record was overwritten')
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary)
    def write(name, rows):
        with (folder/name).open('w', newline='') as stream:
            writer = csv.writer(stream);writer.writerow(NAMES);writer.writerow(('Radix - HEX',)*4);writer.writerows(rows)
    original = [[1, f'{i:x}', f'{i:x}', 0] for i in range(2048)]
    write('good.csv', original)
    assert read_chunk(folder/'good.csv', 0, 0) == list(range(2048));checks += 1
    for change in ('short', 'duplicate', 'reorder', 'mixed', 'invalid', 'overflow'):
        rows = [r.copy() for r in original]
        if change == 'short': rows.pop()
        if change == 'duplicate': rows[1024][2] = rows[1023][2]
        if change == 'reorder': rows[2], rows[3] = rows[3], rows[2]
        if change == 'mixed': rows[0][3] = 1
        if change == 'invalid': rows[0][0] = 0
        if change == 'overflow': rows[0][1] = '40000000'
        write('bad.csv', rows)
        try: read_chunk(folder/'bad.csv', 0, 0)
        except ValueError: checks += 1
        else: raise AssertionError(change+' was accepted')
    for base in range(0, 8192, 2048):
        write(f'transfer_spectrum_{base:05d}.csv', [[1, f'{base+i:x}', f'{base+i:x}', 0] for i in range(2048)])
    scope = [[1, f'{(i%1024)*173:x}', f'{i:x}', 1] for i in range(2048)]
    write('transfer_scope.csv', scope)
    convert(folder, 8192, 17, 14, 1)
    assert len(list(csv.DictReader((folder/'ila.csv').open()))) == 4096
    assert len(list(csv.DictReader((folder/'scope.csv').open()))) == 1024;checks += 1
    scope[-1][1] = '0';write('transfer_scope.csv', scope)
    try: convert(folder, 8192, 17, 14, 1)
    except ValueError: checks += 1
    else: raise AssertionError('Mixed snapshot accepted')

def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
old=load('old_plot', ROOT.parent/'measurement_console_parallel/plotting.py')
new=load('new_plot', ROOT.parents[2]/'deliverables/ui_professional/measurement_console_route_opt/plotting.py')
rng=np.random.default_rng(61006)
cases=[]
for n in (8192,16384):
    for values in (rng.integers(0,1<<30,n), np.ones(n), np.zeros(n)):
        for low, high in ((-250,250),(-1.5,1.5),(120,240)):
            args=(values,500e6,low,high,(64,1460,24,800))
            assert np.allclose(old.spectrum_points(*args),new.spectrum_points(*args),rtol=0,atol=1e-10)
            cases.append(args);checks += 1
args=cases[0]
def timing(function):
    times=[]
    for _ in range(12):
        start=time.perf_counter();function(*args);times.append((time.perf_counter()-start)*1000)
    return float(np.median(times))
old_ms,new_ms=timing(old.spectrum_points),timing(new.spectrum_points)
for n in (8192,16384):
    values=rng.uniform(-120,5,n)
    cold,hot=np.array([23,29,36]),np.array([221,226,230])
    expected=['#%02x%02x%02x'%tuple(np.rint(cold+(hot-cold)*np.clip((float(group.max())+80)/80,0,1)).astype(int)) for group in np.array_split(values,1396)]
    assert new.waterfall_colors(values,1396)==expected;checks += 1
paths=[ROOT/'host/bulk_capture.py',ROOT/'scripts/live_bridge.tcl',ROOT.parents[2]/'deliverables/ui_professional/measurement_console_route_opt/plotting.py']
report=dict(passed=True,checks=checks,source='offline_integrity_and_rendering',plot_old_median_ms=old_ms,plot_new_median_ms=new_ms,
    plot_speedup=old_ms/new_ms,source_sha256={os.path.relpath(p,ROOT).replace(chr(92),chr(47)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(ROOT/'results/transport_offline_verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},ensure_ascii=False))
