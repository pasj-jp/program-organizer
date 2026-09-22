"""Export the scheduled program using the PASJ JSON format."""

import json
from io import BytesIO

from .pasj_program_to_json import convert_row, read_xlsx
from .program_excel import export_program


def export_program_json(meeting):
    """Convert program.xlsx in memory, preserving the original PASJ format."""
    rows = read_xlsx(BytesIO(export_program(meeting)))
    return json.dumps([convert_row(row) for row in rows], ensure_ascii=False, indent=4)
