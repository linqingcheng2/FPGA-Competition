from portable_tools import vivado_bin
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1]
WORK=(ROOT/'../../../work/route_opt_clock4_unit').resolve();WORK.mkdir(exist_ok=True)
(WORK/'tb.v').write_text('''`timescale 1ns/1ps
module tb_clock;
 reg input_clk=0;always #4 input_clk=~input_clk;
 reg button_reset=1;
 wire direct_clk,direct_reset,direct_locked,slow_clk,slow_reset,slow_locked;
 parallel_clock #(.DIVIDE(8)) direct(.clk_125(input_clk),.external_reset(button_reset),.clk(direct_clk),.reset(direct_reset),.locked(direct_locked));
 parallel_clock #(.DIVIDE(10)) slow(.clk_125(input_clk),.external_reset(button_reset),.clk(slow_clk),.reset(slow_reset),.locked(slow_locked));
 integer direct_edges=0,slow_edges=0,trial,j,start_direct,start_slow;
 realtime previous_edge=0;
 always @(posedge direct_clk)begin
  if(direct_edges>0 && $realtime-previous_edge!=8.0)$fatal(1,"DIRECT_CLOCK_STOPPED_OR_CHANGED");
  direct_edges=direct_edges+1;previous_edge=$realtime;
 end
 always @(posedge slow_clk)slow_edges=slow_edges+1;
 initial begin
  repeat(10)@(negedge input_clk);
  if(!direct_reset || direct_locked)$fatal(1,"INITIAL_RESET");
  for(trial=0;trial<8;trial=trial+1)begin
   @(negedge input_clk);#1;button_reset=1;#0.1;
   if(!direct_reset || direct_locked)$fatal(1,"ASYNC_ASSERT");
   start_direct=direct_edges;repeat(12)@(negedge input_clk);
   if(direct_edges-start_direct!=12)$fatal(1,"DEBUG_CLOCK_MUST_RUN_DURING_RESET");
   #1;button_reset=0;
   for(j=0;j<4;j=j+1)begin
    @(posedge direct_clk);#0.1;
    if(direct_reset!==(j<3))$fatal(1,"RESET_RELEASE_CYCLE %0d",j);
   end
  end
  wait(slow_locked && !slow_reset);repeat(10)@(negedge input_clk);
  start_direct=direct_edges;start_slow=slow_edges;#2000;
  if(direct_edges-start_direct!=250)$fatal(1,"125_MHZ_RATE");
  if(slow_edges-start_slow<199 || slow_edges-start_slow>201)$fatal(1,"100_MHZ_RATE");
  $display("CLOCK4_PASS direct125 uninterrupted reset + alternate100");$finish;
 end
 initial begin #200000;$fatal(1,"CLOCK_TIMEOUT");end
endmodule
''',encoding='utf-8')
B=vivado_bin()
commands=([str(B/'xvlog.bat'),str(ROOT/'rtl/parallel_clock.v'),str(vivado_bin().parent/'data/verilog/src/glbl.v'),'tb.v'],[str(B/'xelab.bat'),'tb_clock','glbl','-L','unisims_ver','-L','secureip','-s','clock_snapshot'],[str(B/'xsim.bat'),'clock_snapshot','-runall'])
for args in commands:
    r=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (WORK/(Path(args[0]).stem+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-2500:])
    if 'xsim.bat' in args[0]:assert 'CLOCK4_PASS' in r.stdout,r.stdout[-2000:]
(ROOT/'results/clock4_verification.json').write_text(json.dumps(dict(passed=True,direct_clock_hz=125000000,alternate_clock_hz=100000000,reset_assertion_async=True,reset_release_cycles=4,clock_uninterrupted_during_reset=True,source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('rtl/parallel_clock.v','scripts/board.xdc')}),indent=2),encoding='utf-8')
print('CLOCK4_PASS direct125 uninterrupted reset + alternate100',flush=True)
