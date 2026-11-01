from portable_tools import vivado_bin
"""Exact RMS and unique metadata at full throughput, with gaps and live resets."""
from pathlib import Path
import csv
import datetime
import hashlib
import json
import math
import random
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = (ROOT / '../../../work/route_opt_rms_pipeline_unit').resolve()
WORK.mkdir(exist_ok=True)
rng = random.Random(20261009)
vectors = []
for cycle in range(6000):
    reset = cycle < 8 or cycle in (332, 333, 4094, 4095, 4096)
    valid = not reset and (cycle < 400 or rng.randrange(4) != 0)
    count = (1, 2, 3, 32767, 32768, rng.randrange(1, 32769))[cycle % 6]
    mean = (0, 1, 2, 8388608, rng.randrange(8388609))[cycle % 5]
    energy = mean * count + (rng.randrange(count) if mean < 8388608 else 0)
    metadata = (rng.getrandbits(144) << 32) | cycle
    vectors.append((reset, valid, energy, count, metadata))
vectors.extend([(False, False, 0, 1, 0)] * 100)
(WORK / 'jobs.mem').write_text(''.join(
    f'{(int(reset)<<257)|(int(valid)<<256)|(energy<<208)|(count<<176)|metadata:065x}\n'
    for reset, valid, energy, count, metadata in vectors), encoding='ascii')
bench = r'''`timescale 1ns/1ps
module tb_rms_jobs;
 reg clk=0;always #4 clk=~clk;
 reg rst=1,valid=0;reg [47:0] energy=0;reg [31:0] count=1;
 reg [175:0] metadata=0;wire out_valid;wire [11:0] root;wire [175:0] returned;
 rms_pipeline dut(.clk(clk),.rst(rst),.in_valid(valid),.in_energy(energy),
  .in_count(count),.in_metadata(metadata),.out_valid(out_valid),.out_rms(root),.out_metadata(returned));
 reg [257:0] jobs[0:SAMPLES-1];integer k,f,input_cycle=-1;
 initial begin
  $readmemh("jobs.mem",jobs);f=$fopen("results.csv","w");
  $fwrite(f,"cycle,rms,metadata\n");
  for(k=0;k<SAMPLES;k=k+1)begin
   @(negedge clk);input_cycle=k;{rst,valid,energy,count,metadata}=jobs[k];
  end
  @(negedge clk);rst=1;@(negedge clk);$fclose(f);
  $display("RMS_JOBS_SIMULATION_COMPLETE");$finish;
 end
 always @(posedge clk)begin #1;
  if(out_valid)$fwrite(f,"%0d,%0d,%044h\n",input_cycle,root,returned);
 end
 initial begin #100000;$fatal(1,"RMS jobs timeout");end
endmodule
'''.replace('SAMPLES', str(len(vectors))).replace(r'\"', '"')
(WORK / 'tb.v').write_text(bench, encoding='ascii')
B = vivado_bin()
for command in ([str(B / 'xvlog.bat'), str(ROOT / 'rtl/rms_pipeline.v'), 'tb.v'],
        [str(B / 'xelab.bat'), 'tb_rms_jobs', '-s', 'rms_jobs_snapshot'],
        [str(B / 'xsim.bat'), 'rms_jobs_snapshot', '-runall']):
    result = subprocess.run(command, cwd=WORK, capture_output=True, text=True,
        encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    output = result.stdout + result.stderr
    (WORK / (Path(command[0]).stem + '.log')).write_text(output, encoding='utf-8')
    assert result.returncode == 0, output[-4000:]
assert 'RMS_JOBS_SIMULATION_COMPLETE' in output and 'Fatal:' not in output, output[-4000:]
expected = []
for cycle, (reset, valid, energy, count, metadata) in enumerate(vectors):
    if valid and not reset and not any(row[0] for row in vectors[cycle:cycle+38]):
        expected.append((cycle+37, math.isqrt(energy // count), metadata))
actual = [(int(row['cycle']), int(row['rms']), int(row['metadata'], 16))
    for row in csv.DictReader((WORK / 'results.csv').open(encoding='ascii'))]
assert actual == expected, (len(actual), len(expected), [(a, b) for a, b in zip(actual, expected) if a != b][:3])
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
paths = (ROOT / 'rtl/rms_pipeline.v', Path(__file__))
report = dict(passed=True, source='actual_RTL_with_independent_integer_square_root_and_unique_metadata',
    board_test=False, exact_jobs=len(expected), input_cycles=len(vectors), latency_clocks=37,
    checks=['one_job_every_clock', 'random_valid_gaps', 'live_reset_discards_in_flight_jobs',
        'all_176_metadata_bits', 'floor_sqrt_floor_energy_div_count', 'minimum_and_maximum_count'],
    completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    source_sha256={str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in paths},
    output_sha256={p.name: digest(p) for p in WORK.iterdir() if p.suffix in ('.log', '.mem', '.csv', '.v')})
(ROOT / 'results/rms_pipeline_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('RMS_FULL_THROUGHPUT_UNIQUE_METADATA_EXACT_PASS', len(expected))
