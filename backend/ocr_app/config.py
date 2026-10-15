from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = {'glm_ocr': 'glm-ocr', 'paddleocr_vl': 'paddleocr-vl'}
MODES = ('dual_resident', 'single_resident')


@dataclass(frozen=True)
class RuntimeConfig:
    session_dir: Path
    mode: str = 'dual_resident'
    load_timeout: float = 300.0
    request_timeout: float = 180.0
    data_root: Path | None = None

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError('Unknown residency mode')
        if self.load_timeout <= 0 or self.request_timeout <= 0:
            raise ValueError('Timeout must be positive')

    def model_command(self, key):
        model = MODELS[key]
        return [str(ROOT / '.venvs' / model / 'Scripts/python.exe'), '-u', '-X', 'utf8',
                str(ROOT / 'backend/model_worker.py'), '--model', model]
