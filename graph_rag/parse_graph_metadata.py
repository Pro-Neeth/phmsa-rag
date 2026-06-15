import re


def parse_metadata(text_content: str, filename: str) -> dict:

    metadata = {
        "Filename": filename,
        "URL": None,
        "Subject": None,
        "Date of Failure": None,
        "Commodity Released": None,
        "City, County, and State": None,
        "OpID & Operator Name": None,
        "Unit # & Unit Name": None,
        "SMART Activity #": None,
        "Milepost/Location": None,
        "Type of Failure": None,
    }

    # Subject line (appears before the first ## section)
    subject_match = re.search(
        r'^Subject\s*\n\s*(.+?)(?=\n\n|\n##)',
        text_content,
        re.MULTILINE | re.DOTALL,
    )
    if subject_match:
        metadata["Subject"] = subject_match.group(1).strip()

    # Each tuple: (vertical_layout_pattern, table_layout_pattern, metadata_key)
    field_patterns = [
        (
            r'Date of Failure\s*\n\s*([^\n]+)',
            r'\|\s*Date of Failure\s*\|\s*([^\|\n]+?)\s*\|',
            'Date of Failure',
        ),
        (
            r'Commodity Released\s*\n\s*([^\n]+)',
            r'\|\s*Commodity Released\s*\|\s*([^\|\n]+?)\s*\|',
            'Commodity Released',
        ),
        (
            r'City[/,]?\s*Parish[,\s]*&?\s*State\s*\n\s*([^\n]+)',
            r'\|\s*City[,\s]*Parish[,\s]*(?:and|&)\s*State\s*\|\s*([^\|\n]+?)\s*\|',
            'City, County, and State',
        ),
        (
            r'OpID\s*&\s*Operator Name\s*\n\s*([^\n]+)',
            r'\|\s*OpID\s*(?:and|&)\s*Operator Name\s*\|\s*([^\|\n]+?)\s*\|',
            'OpID & Operator Name',
        ),
        (
            r'Unit\s*#\s*&\s*Unit Name\s*\n\s*([^\n]+)',
            r'\|\s*Unit\s*#\s*(?:and|&)\s*Unit Name\s*\|\s*([^\|\n]+?)\s*\|',
            'Unit # & Unit Name',
        ),
        (
            r'(?:SMART|WMS)\s*Activity\s*#\s*\n\s*([^\n]+)',
            r'\|\s*(?:SMART|WMS)Activity\s*#\s*\|\s*([^\|\n]+?)\s*\|',
            'SMART Activity #',
        ),
        (
            r'Milepost\s*[/\s]*Location\s*\n\s*([^\n]+)',
            r'\|\s*Milepost\s*[/\s]*Location\s*\|\s*([^\|\n]+?)\s*\|',
            'Milepost/Location',
        ),
        (
            r'Type of Failure\s*\n\s*([^\n]+)',
            r'\|\s*Type of Failure\s*\|\s*([^\|\n]+?)\s*\|',
            'Type of Failure',
        ),
    ]

    # Field values are found inside the Operator, Location & Consequences section
    operator_section_match = re.search(
        r'##\s*Operator,?\s*Location,?\s*&?\s*Consequences\s*\n(.*?)(?=\n##|\Z)',
        text_content,
        re.DOTALL | re.IGNORECASE,
    )

    search_scope = operator_section_match.group(1) if operator_section_match else text_content

    for vertical_pattern, table_pattern, key in field_patterns:
        match = re.search(vertical_pattern, search_scope, re.IGNORECASE)
        if match:
            metadata[key] = match.group(1).strip()
        else:
            match = re.search(table_pattern, search_scope, re.IGNORECASE)
            if match:
                metadata[key] = match.group(1).strip()

    return metadata
