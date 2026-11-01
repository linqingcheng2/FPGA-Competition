from portable_tools import vivado_bin
"""Exercise the actual RTL rounding definitions against exact integer arithmetic."""
from pathlib import Path
import random,re,hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1];WORK=(ROOT/'../../../work/route_opt_rounding_unit').resolve();WORK.mkdir(exist_ok=True)
rtl=(ROOT/'rtl/fft4.v').read_text();functions='\n'.join(re.findall(r' function .*?endfunction',rtl,re.S))
assert len(re.findall('endfunction',functions))==4
rng=random.Random(20261008);tests=[]
def convergent(v,amount):
    if amount==0:return v
    whole,remainder=divmod(v,1<<amount);half=1<<(amount-1)
    return whole+int(remainder>half or remainder==half and whole&1)
for amount in range(25):
    values=[-131072,-131071,-65537,-65536,-3,-2,-1,0,1,2,3,65535,131070,131071]+[rng.randrange(-131072,131072) for _ in range(1024)]
    tests.extend((0,v,amount,convergent(v,amount)) for v in values)
for kind,shift,bound in ((1,16,131072*92682),(2,3,741456),(3,4,1<<35)):
    values=[0,1,(1<<shift)//2-1,(1<<shift)//2,(1<<shift)//2+1,(1<<shift)+(1<<shift)//2,bound-1]
    values += [rng.randrange(0,bound) for _ in range(10000)]
    if kind!=3:values += [-v for v in values]
    tests.extend((kind,v,shift,convergent(v,shift)) for v in values)
(WORK/'values.mem').write_text(''.join(f'{kind:01x}{value&((1<<37)-1):010x}{amount:02x}{expected&0xffffffff:08x}\n' for kind,value,amount,expected in tests))
tb='''`timescale 1ns/1ps
module tb_rounding;
FUNCTIONS
reg [83:0] tests[0:COUNT-1];reg signed [36:0] value;reg [7:0] amount;reg [31:0] actual,expected;reg [18:0] parts;integer n;
initial begin
 $readmemh("values.mem",tests);
 for(n=0;n<COUNT;n=n+1)begin
  value=tests[n][79:40];amount=tests[n][39:32];expected=tests[n][31:0];
  case(tests[n][83:80])
   0:begin parts=align_shift_and_guard(value[17:0],amount);actual=$signed(parts[17:0])+$signed({1'b0,parts[18]});end
   1:actual=$signed(round_rotate(value));
   2:actual=$signed(round_combine(value[20:0]));
   3:actual=round_power(value);
  endcase
  if(actual!==expected)$fatal(1,"ROUNDING_MISMATCH case=%0d value=%0d amount=%0d actual=%0d expected=%0d",n,value,amount,$signed(actual),$signed(expected));
 end
 $display("PRECISION_ROUNDING_PASS COUNT");$finish;
end
endmodule
'''.replace('FUNCTIONS',functions).replace('COUNT',str(len(tests)))
(WORK/'tb.v').write_text(tb)
B=vivado_bin()
for args in ([str(B/'xvlog.bat'),'tb.v'],[str(B/'xelab.bat'),'tb_rounding','-s','rounding_snapshot'],[str(B/'xsim.bat'),'rounding_snapshot','-runall']):
    r=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (WORK/(Path(args[0]).stem+'.log')).write_text(r.stdout+r.stderr)
    assert r.returncode==0,(r.stdout+r.stderr)[-2000:]
    if 'xsim.bat' in args[0]:assert f'PRECISION_ROUNDING_PASS {len(tests)}' in r.stdout and 'Fatal:' not in r.stdout,r.stdout[-2500:]
names=['rtl/fft4.v','scripts/check_precision_rounding.py']
(ROOT/'results/precision_rounding_verification.json').write_text(json.dumps(dict(passed=True,cases=len(tests),method='actual_RTL_functions_vs_independent_exact_integer_ties_even_reference',covers=['signed_alignment_0_to_24_bits','twiddle_guard_width','radix4_combine','public_power'],source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}),indent=2))
print('PRECISION_ROUNDING_PASS',len(tests))
