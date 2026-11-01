"""Compare compressed ROM reconstruction with the original complete tables."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
cos=[int(w,16) for w in (ROOT/'rtl/twiddle_cos.mem').read_text().split()];assert len(cos)==4096
checked=0
for lane in (1,2,3):
 words=[int(w,16) for w in (ROOT/f'rtl/twiddle{lane}.mem').read_text().split()]
 for k,word in enumerate(words):
  q,x=divmod(k*lane,4096);c=cos[x];v=cos[4096-x] if x else 0
  re,im=((c,-v),(-v,-c),(-c,v),(v,c))[q]
  assert ((re&0x3ffff)|((im&0x3ffff)<<18))==word,(lane,k)
  checked+=1
names=['rtl/twiddle_cos.mem','rtl/twiddle1.mem','rtl/twiddle2.mem','rtl/twiddle3.mem','rtl/fft4.v','scripts/check_coefficients.py']
(ROOT/'results/coefficients_verification.json').write_text(json.dumps(dict(passed=True,coefficients=checked,bit_exact=True,
 source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}),indent=2))
print('EXACT_COEFFICIENT_PACKING_PASS',checked)
