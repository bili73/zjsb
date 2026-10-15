"""Serial interview-form pipeline benchmark; production must be idle and stopped.

Raw fields, originals and attempt text are encrypted in a fresh output directory.
Anonymous CSV measures elapsed time and field presence, not correctness.
"""
import argparse
from pathlib import Path

from probe_bank_photocopy import pipeline_probe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    pipeline_probe(parser.parse_args(), doc_type='INTERVIEW_FORM')
