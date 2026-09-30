#!/usr/bin/env python3
"""Recheck reversed-pair PATCH and collective-move no-op contracts."""
import argparse

from stage3_independent import check_combined_table_history

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("base_url", help="disposable Stage 3 service")
check_combined_table_history(parser.parse_args().base_url)
