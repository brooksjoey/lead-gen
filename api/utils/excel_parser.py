"""Excel file parser for bulk lead ingestion."""
from __future__ import annotations

import io
from typing import Dict, List, Optional

import pandas as pd

from api.core.logging import get_structlog_logger

logger = get_structlog_logger()


def parse_excel_leads(
    file_content: bytes,
    sheet_name: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Parse Excel file and return list of lead dictionaries.
    
    Expected columns: name, email, phone, postal_code, city, message, etc.
    """
    try:
        # Read Excel file
        excel_file = io.BytesIO(file_content)
        
        # Try to read the file
        try:
            df = pd.read_excel(
                excel_file,
                sheet_name=sheet_name or 0,
                engine="openpyxl",
            )
        except Exception:
            # Try with xlrd engine for older .xls files
            excel_file.seek(0)
            df = pd.read_excel(excel_file, sheet_name=sheet_name or 0, engine="xlrd")
        
        # Convert to list of dictionaries
        leads = []
        for idx, row in df.iterrows():
            try:
                # Convert row to dict, cleaning up values
                lead_data = {}
                for col, val in row.items():
                    if pd.notna(val):
                        # Convert to string and strip
                        str_val = str(val).strip()
                        if str_val:
                            lead_data[col.strip()] = str_val
                
                # Skip empty rows
                if not lead_data:
                    continue
                
                leads.append(lead_data)
                
            except Exception as e:
                logger.warning(
                    "excel_parser.row_error",
                    row_number=idx + 2,  # +2 because Excel is 1-indexed and has header
                    error=str(e),
                )
                continue
        
        logger.info(
            "excel_parser.parsed",
            total_rows=len(leads),
            sheet_name=sheet_name,
        )
        
        return leads
        
    except Exception as e:
        logger.error("excel_parser.parse_error", error=str(e))
        raise ValueError(f"Failed to parse Excel file: {str(e)}")

