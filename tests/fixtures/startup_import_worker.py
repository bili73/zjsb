"""Use the actual worker protocol with CPU-only lazy numerical imports."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
import model_worker

class ImportEngine:
    model=None
    phase='loading'
    def __init__(self,*args):pass
    def load(self):
        import numpy
        self.model=object()
        return dict(revision='cpu-import',numpy=numpy.__version__)
    def recognize(self,payload):return dict(text='synthetic',termination_reason='eos')

model_worker.Engine=ImportEngine
model_worker.main()
