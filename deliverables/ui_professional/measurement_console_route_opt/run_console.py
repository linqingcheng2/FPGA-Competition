"""Open a real archived frame; no automatic hardware operation."""
from pathlib import Path
import argparse
import json
import os
import datetime
import traceback
import sys

ENTRY=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('record',nargs='?',type=Path)
parser.add_argument('--version',type=int,choices=(500,),default=500)
parser.add_argument('--activate',action='store_true')
parser.add_argument('--comparison',action='store_true')
parser.add_argument('--cable',default='')
parser.add_argument('--vivado',default='')
args=parser.parse_args()
from single_instance import show_existing,install
from vivado_locator import find_vivado
if args.version==500 and show_existing(ENTRY/'runtime'):raise SystemExit(0)
from console import EngineeringConsole,HERE,PROJECT,load_record

runtime = HERE/'runtime'
runtime.mkdir(exist_ok=True)
try:
    app = EngineeringConsole()
    if args.version==500:install(app,runtime)
    app.cable_filter.set('' if args.cable in ('', 'Digilent', 'auto', '自动发现') else args.cable)
    try:
        app.vivado.set(find_vivado(args.vivado))
    except FileNotFoundError as error:
        # Keep the window usable so the user can enter a path in diagnostics.
        app.vivado.set(args.vivado)
        app.progress_note.set(str(error))
        app.diagnostic.insert('end', '\n' + str(error) + '\n')
    current=PROJECT/'results/board'/('third_matrix_20261004' if args.version==125 else 'parallel_matrix')/'run_1/tone8k'
    proof=PROJECT/'results/parallel_board_verification.json'
    if args.version==500 and proof.exists():
        report=json.loads(proof.read_text(encoding='utf-8'))
        if report.get('passed') and report.get('complete'):
            tone=next((row for row in report.get('tests',[]) if row['case']=='tone8k'),None)
            if tone:current=Path(tone['transport']['folder'])
    folder = args.record or current
    if (folder/'measurement.json').exists():
        app.update_idletasks()
        load_record(app, folder)
        if args.comparison:
            app.comparison_enabled.set(True);app.record_reference(quiet=True)
            app.notebook.select(app.tabs['参考对比'])
    app.state('zoomed')
    def ready():
        app.lift()
        app.focus_force()
        (runtime/'ready.json').write_text(json.dumps(dict(pid=os.getpid(), title=app.title(),
            record=str(folder), theme='laboratory', comparison_enabled=app.comparison_enabled.get(),
            started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            auto_connect=args.activate,selected_version=args.version,experiment_clock_hz=args.version*1000000,
            displayed_frame_clock_hz=app.metric.get('fs') if app.metric else None,
            displayed_frame_historical=True if app.metric else None), ensure_ascii=False, indent=2), encoding='utf-8')
        if args.activate:app.version_controller.activate()
    app.after(300, ready)
    app.mainloop()
except Exception:
    (runtime/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
    raise


