from __future__ import annotations
import io
import pandas as pd

def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Competenze") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buffer.getvalue()
