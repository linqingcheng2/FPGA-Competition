"""Find a usable local Vivado launcher after a project is moved."""
from __future__ import annotations

import os
from pathlib import Path


def _as_launcher(value):
    if not value:
        return None
    path = Path(str(value).strip().strip('"')).expanduser()
    if path.name.lower() == "vivado.bat":
        return path
    if path.name.lower() == "vivado.exe":
        # The unwrapped executable does not initialize the DLL/data paths.
        for parent in path.parents:
            if parent.name.lower() == "bin":
                return parent / "vivado.bat"
        return path.with_suffix(".bat")
    return path / "vivado.bat" if path.name.lower() == "bin" else path / "bin" / "vivado.bat"


def _candidate_paths():
    seen = set()

    def add(value):
        candidate = _as_launcher(value)
        if candidate is None:
            return
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            yield candidate

    for value in (os.environ.get("VIVADO_PATH"), os.environ.get("XILINX_VIVADO"),
                  os.environ.get("VIVADO_ROOT")):
        yield from add(value)
    for root in (Path("C:/Xilinx/Vivado"), Path("D:/Xilinx/Vivado"),
                 Path("C:/Program Files/Xilinx/Vivado"), Path("D:/vivado/Vivado")):
        if root.is_dir():
            for version in sorted(root.iterdir(), reverse=True):
                if version.is_dir():
                    yield from add(version)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if folder:
            yield from add(Path(folder) / "vivado.bat")
            yield from add(Path(folder) / "vivado.exe")


def find_vivado(requested=""):
    """Return an existing Vivado launcher, preferring the requested path."""
    candidates = []
    if requested:
        candidates.append(_as_launcher(requested))
    candidates.extend(_candidate_paths())
    for candidate in candidates:
        if candidate is not None:
            try:
                if candidate.is_file() and candidate.suffix.lower() == ".bat":
                    return str(candidate.resolve())
            except OSError:
                pass
    raise FileNotFoundError(
        "找不到 Vivado 启动器。请在‘诊断与上板’中填写 vivado.bat 的完整路径，"
        "或设置 VIVADO_PATH / XILINX_VIVADO 环境变量。"
    )

