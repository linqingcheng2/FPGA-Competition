"""Offline UI smoke check. Never connects or programs a device."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
repo=ROOT.parents[2]
sys.path.insert(0,str(repo/'deliverables/ui_professional/measurement_console_route_opt'))
from console import EngineeringConsole,PROJECT
app=EngineeringConsole()
try:
    app.withdraw();app.update_idletasks();app.update()
    assert PROJECT==ROOT
    assert app.session is None and not app.connected
    assert app.version_id==500
    assert set(app.version_buttons)=={500}
    assert len(app.tabs)>=3
    assert app.parameters()['n'] in (8192,16384)
    for key in ('connect','capture','preview'): assert key in app.action_buttons
    print('OFFLINE_UI_PASS',app.title(),len(app.tabs))
finally:
    for timer in app.tk.splitlist(app.tk.call('after','info')): app.after_cancel(timer)
    app.destroy()
