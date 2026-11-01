"""Actual-board, paired transport profiles; every capture must validate first."""
from pathlib import Path
import argparse, datetime, hashlib, json, sys, time
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from live_transport import LiveSession,verify_firmware
from bench import bench_case
from capture import load_hardware

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--power-source',choices=('usb','external_5v'),required=True);args=parser.parse_args()
    firmware=verify_firmware()
    run=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'results/board/transport_benchmark'/run;folder.mkdir(parents=True)
    cases={c['name']:c for c in json.loads((ROOT/'vectors/manifest.json').read_text())}
    report=dict(firmware_hashes=firmware['hashes'],source='actual_board_paired_transport',power_source=args.power_source,power_source_declared_by='operator_command_line',bit_sha256=firmware['hashes']['results/competition.bit'],
        folder=str(folder),passed=False,complete=False,profiles=[],cached=[],readback=[])
    def save():
        data=json.dumps(report,indent=2)
        (folder/'verification.json').write_text(data)
        (ROOT/'results/transport_board_verification.json').write_text(data)
    session=LiveSession(cable_filter='210351A8220B')
    try:
        session.call('connect');session.call('program')
        golden=None
        profiles=[(5000000,'ports',8),(5000000,'core',8),(15000000,'core',8),(30000000,'core',8),(15000000,'core',16),(15000000,'core',32),(30000000,'core',32)]
        for i,(hz,commit,window) in enumerate(profiles):
            tune=session.call('tune',hz,commit,'bulk',window)
            result=bench_case(cases['tone8k'],folder/f'profile_{i}',session.vivado,transport=session,scope_capture=True)
            assert result['passed'],result
            _,power,_=load_hardware(Path(result['transport']['folder']))
            if golden is None:golden=power.copy()
            assert np.array_equal(power,golden),'Transport changed spectrum'
            report['profiles'].append(dict(tune=tune,result=result,spectrum_bit_exact=True));save()
            print('PROFILE',hz,commit,window,'load_ms',result['transport']['load_ms'],'spectrum_ms',result['transport']['spectrum_transfer_ms'],flush=True)
        fastest=min(report['profiles'],key=lambda row:int(row['result']['transport']['elapsed_ms']))
        report['recommended']=fastest['tune'];selected=fastest['tune']
        session.call('tune',selected['jtag_hz'],selected['commit_mode'],'bulk',selected['upload_ack_window'])
        for name in ('tone8k','tone16k'):
            result=bench_case(cases[name],folder/f'cold_{name}',session.vivado,transport=session,scope_capture=True)
            assert result['passed'];report['cached'].append(dict(state='cold',result=result));save()
            for repeat in range(3):
                result=bench_case(cases[name],folder/f'cached_{name}_{repeat}',session.vivado,transport=session,scope_capture=True)
                assert result['passed'] and int(result['transport']['reused_vector'])==1
                report['cached'].append(dict(state='cached',result=result));save()
                print('CACHED',name,result['transport']['elapsed_ms'],flush=True)
        # Same implemented algorithm, input and USB link; only readback changes.
        for mode in ('vio','bulk'):
            session.call('tune',5000000,'ports',mode,8)
            result=bench_case(cases['tone8k'],folder/f'readback_{mode}',session.vivado,transport=session,scope_capture=True)
            assert result['passed'];report['readback'].append(dict(mode=mode,result=result));save()
            print('READBACK',mode,result['transport']['spectrum_transfer_ms'],result['transport'].get('scope_transfer_ms'),flush=True)
        report.update(passed=True,complete=True,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            zero_faults=True,all_scope_pairs_exact=True,profile_spectra_bit_exact=True,transport_recoveries=len(session.recoveries))
        assert not session.recoveries
        save();print('TRANSPORT_PAIRED_BOARD_PASS',flush=True)
    except Exception as error:
        report['error']=str(error);save();raise
    finally:session.close()

if __name__=='__main__':main()
