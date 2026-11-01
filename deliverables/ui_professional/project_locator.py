"""Resolve the 500 MSPS project inside this repository."""
from pathlib import Path
import os
def resolve_project(version):
    if version != 500: raise ValueError('This repository contains only the 500 MSPS profile')
    repo=Path(__file__).resolve().parents[2]
    project=Path(os.environ.get('BASEBAND_PROJECT_500',repo/'outputs/parallel_baseband/competition_project_route_opt'))
    if not (project/'host/app.py').is_file(): raise FileNotFoundError(str(project))
    return project.resolve()
