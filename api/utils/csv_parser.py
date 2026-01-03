"""CSV file parser for bulk lead ingestion."""
from __future__ import annotations

import csv
import io
from typing import Dict, List, Optional

from api.core.logging import get_structlog_logger

logger = get_structlog_logger()


def parse_csv_leads(
    file_content: bytes,
    encoding: str = "utf-8",
    delimiter: str = ",",
) -> List[Dict[str, str]]:
    """
    Parse CSV file and return list of lead dictionaries.
    
    Expected columns: name, email, phone, postal_code, city, message, etc.
    """
    try:
        # Decode file content
        text_content = file_content.decode(encoding)
        
        # Parse CSV
        reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)
        
        leads = []
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            try:
                # Clean up row data
                lead_data = {
                    k.strip(): v.strip() if v else None
                    for k, v in row.items()
                    if k and k.strip()
                }
                
                # Skip empty rows
                if not any(lead_data.values()):
                    continue
                
                leads.append(lead_data)
                
            except Exception as e:
                logger.warning(
                    "csv_parser.row_error",
                    row_number=row_num,
                    error=str(e),
                )
                continue
        
        logger.info(
            "csv_parser.parsed",
            total_rows=len(leads),
            encoding=encoding,
        )
        
        return leads
        
    except UnicodeDecodeError as e:
        logger.error("csv_parser.decode_error", encoding=encoding, error=str(e))
        raise ValueError(f"Failed to decode CSV file with encoding {encoding}")
    except csv.Error as e:
        logger.error("csv_parser.parse_error", error=str(e))
        raise ValueError(f"Failed to parse CSV file: {str(e)}")
    except Exception as e:
        logger.error("csv_parser.unexpected_error", error=str(e))
        raise ValueError(f"Unexpected error parsing CSV: {str(e)}")

