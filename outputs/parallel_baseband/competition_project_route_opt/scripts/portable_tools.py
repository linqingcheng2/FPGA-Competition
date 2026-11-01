"""Locate Vivado tools for command-line component checks."""
from pathlib import Path
import os, shutil
def vivado_bin():
    value=os.environ.get('VIVADO_PATH') or os.environ.get('XILINX_VIVADO') or shutil.which('vivado.bat')
    if not value: raise RuntimeError('Set VIVADO_PATH to Vivado 2025.2 bin/vivado.bat')
    p=Path(value)
    p=p.parent if p.suffix.lower() in ('.bat','.exe') else (p if p.name=='bin' else p/'bin')
    if not (p/'xsim.bat').is_file(): raise FileNotFoundError(str(p/'xsim.bat'))
    return p
