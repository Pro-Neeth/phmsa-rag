import os
import re
import sys
import unicodedata

from clean_md import (
    JUNK_PATTERN,
    OPERATOR_HEADING,
    collapse_intra_section_blanks,
    extract_subject,
    rejoin_broken_lists,
    rejoin_page_break_paragraphs,
    remove_repeated_page_headers,
    split_sentences,
    strip_figure_captions,
    strip_footer_artifacts,
    strip_letterhead_preamble,
)


''' Cleans the oversized reports in data/md/exempt/.

These were held back from clean_md.py because that script truncates at the
first "## APPE" heading. In these documents the appendix is 73-97% of the text
and carries the bulk of the root-cause evidence: embedded consultant reports
(DNV GL, Mears, Kiefner, Stress Engineering) and the PHMSA form narratives.
Cutting there would throw away the analysis the reports exist to convey.

The strategy is the inverse of clean_md.py: instead of keeping everything up to
the appendix, keep the front matter plus the specific blocks inside the appendix
that carry causal analysis, and drop the rest (forms, photo logs, ILI tallies,
vendor manuals).
'''


# The appendix does not always announce itself as "APPENDIX" - the Enbridge
# memos and Chevron use "EXHIBITS".
APPENDIX_MARKER = re.compile(r'(?im)^##\s*(?:APPE|EXHIBIT|ATTACHMENT|ANNEX)')

# Maps each document family's own section names onto the FIR template, so all
# 16 chunk and filter like the main corpus.
HEADING_ALIASES = [
    (r'(?i)^\d+\.0\s+SUMMARY$',                     'Executive Summary'),
    (r'(?i)^Narrative Summary$',                    'Executive Summary'),
    (r'(?i)^Summary:?$',                            'Executive Summary'),
    (r'(?i)^\d+\.\s*Executive Summary$',            'Executive Summary'),
    (r'(?i)^\d+\.0\s+PIPELINE SYSTEM$',             'System Details'),
    (r'(?i)^\d+\.0\s+DISCUSSION$',                  'Investigation Details'),
    (r'(?i)^\d+\.0\s+EMERGENCY RESPONSE$',          'Emergency Response'),
    (r'(?i)^\d+\.0\s+RETURN TO SERVICE$',           'Summary of Return-to-Service'),
    (r'(?i)^\d+\.0\s+FINDINGS$',                    'Findings and Contributing Factors'),
    (r'(?i)^\d+\.\s*Operator,?\s*Location.*$',      'Operator, Location, & Consequences'),
    (r'(?i)^\d+\.0\s+OPERATOR,?\s*LOCATION.*$',     'Operator, Location, & Consequences'),
    (r'(?i)^\d+\.0\s+SYSTEM DETAILS$',              'System Details'),
    (r'(?i)^\d+\.0\s+EVENTS LEADING.*$',            'Events Leading up to the Failure'),
    (r'(?i)^\d+\.0\s+INVESTIGATION.*$',             'Investigation Details'),
]

# The narrative field of the PHMSA/RSPA incident form. Present in 14 of the 16
# files and often the only place the cause is stated in one sentence.
FORM_NARRATIVE = re.compile(
    r'(?im)^#{1,3}\s*PART\s+[A-Z]\s*[-–]\s*'
    r'(?:NARRATIVE|APPARENT CAUSE)(?![^\n]*\b(?:PREPARER|SIGNATURE)\b)[^\n]*\n'
)

# Where a form narrative ends.
FORM_FOOTER = re.compile(r'(?im)^\s*Form\s+(?:RSPA|PHMSA)\s+F\s*7\d{3}[-.]\d')

# OCR debris from the form's checkbox column: lone letters, and runs of "m"
# separated by slashes.
CHECKBOX_NOISE = re.compile(r'(?m)^\s*[lm18|/\\]{1,3}\s*$\n?')

# An appendix that only points at a document PHMSA withheld - the promised
# metallurgy is not in the text.
STUB_APPENDIX = re.compile(r'(?i)This document is on file at PHMSA')

# A numbered section heading, the skeleton every consultant lab report shares.
TECH_HEADING = re.compile(r'(?m)^#{1,3}\s+\d{1,2}\.\d+(?:\.\d+)*\s+\S|^#{1,3}\s+\d{1,2}\.0\s+[A-Z]')

# Vocabulary that separates a real lab report from a vendor equipment manual,
# which uses the same "1.0 / 2.0 / 3.0" numbering.
METALLURGY_VOCAB = re.compile(
    r'(?i)fractograph|metallograph|charpy|microhardness|tensile test|tensile strength'
    r'|\bSEM\b|\bEDS\b|failure origin|root cause|corrosion|weld|crack'
)

# Headings that carry a consultant report's actual analysis.
ANALYSIS_HEADING = re.compile(
    r'(?i)^#{1,3}\s*(?:\d+(?:\.\d+)*\s+)?'
    r'(?:executive\s+summary|introduction|background|scope|technical\s+approach'
    r'|discussion|results?|conclusions?|findings?|recommendations?|summary\s+and\s+conclusions?'
    r'|analysis|visual\s+examination|metallurgical|failure\s+scenario|observations?'
    r'|methodology|hydrogeologic|precipitation)'
)

# DNV GL writes each root cause as its own numbered heading - "## 2. The
# cathodic protection system was ineffective due to shielding by the thermal
# polyurethane insulation". These read as findings, not section labels.
FINDING_HEADING = re.compile(
    r'(?i)^#{1,3}\s*\d{1,2}[.)]\s+\S.{25,}?'
    r'(?:caus|fail|ineffective|inadequate|insufficient|did not|was not|were not'
    r'|contribut|result|corros|crack|defect|shielding|under-?report)'
)

# Bulk form blocks - the single largest waste in these documents.
FORM_BULK_HEADING = re.compile(
    r'(?i)^#{1,3}\s*PART\s+[A-H]\s*[-–]?\s*(?:KEY|GENERAL)\s+REPORT\s+INFORMATION'
)

# Navigation pages carried over from an embedded report's front matter.
NAVIGATION_HEADING = re.compile(
    r'(?i)^#{1,3}\s*(?:table of contents|list of (?:figures|tables|appendices)'
    r'|contents|distribution list|signature form|about\s)'
)


def split_body_and_appendix(text_content):
    '''Return (front matter, appendix) using the widened marker set.'''

    match = APPENDIX_MARKER.search(text_content)
    if not match:
        return text_content, ''
    return text_content[:match.start()], text_content[match.start():]


def normalize_headings(text_content):
    '''Rename each format's own section names to the FIR template.'''

    def rename(match):
        title = match.group(1).strip()
        for pattern, canonical in HEADING_ALIASES:
            if re.match(pattern, title):
                return '## ' + canonical
        return match.group(0)

    return re.sub(r'(?m)^#{1,3}\s+(.*)$', rename, text_content)


def _is_table_block(block):
    '''True when a block is mostly pipe-table rows or image stubs.'''

    if not block.strip():
        return True
    pipes = block.count('|')
    if pipes > len(block) / 25:
        return True
    images = block.count('<!-- image -->')
    words = len(re.findall(r'\b[a-z]{3,}\b', block))
    return images > 6 and words < images * 20


def trim_trailing_data(block):
    '''Cut a section where its prose gives way to tables or a figure list.

    A consultant report's conclusions run straight into chemistry tables and
    pages of "Figure 12. Photograph of ..." with no heading between, so the
    block splitter cannot separate them. Stop at the first sustained run of
    table rows or captions and keep the analysis above it.
    '''

    lines = block.split('\n')
    run = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_data = (
            stripped.startswith('|')
            or re.match(r'(?i)^-?\s*(?:figure|photo|table)\s*\d+[.:]', stripped)
            or re.match(r'^-\s*\d+\s*-\s', stripped)
        )
        if is_data:
            run += 1
            if run >= 3:
                return '\n'.join(lines[:i - run + 1]).rstrip()
        elif stripped:
            run = 0
    return block.rstrip()


def extract_form_narratives(appendix):
    '''Pull the incident form's narrative field out of the surrounding checkboxes.

    These read as ALL-CAPS prose and frequently state the cause outright, e.g.
    "THE CAUSE OF THE FAILURE WAS THE COMBINED WEIGHT OF THE BLIND FLANGE ...
    ACTING AS AN UNSUPPORTED, CANTILEVERED LOAD ON THE BRANCH CONNECTION."
    '''

    out = []
    for match in FORM_NARRATIVE.finditer(appendix):
        start = match.end()
        footer = FORM_FOOTER.search(appendix, start)
        end = footer.start() if footer else start + 4000
        body = appendix[start:min(end, start + 6000)]

        body = CHECKBOX_NOISE.sub('', body)
        body = re.sub(r'(?m)^\s*\(Attach additional sheets as necessary\)\s*$\n?', '', body)
        body = re.sub(r'(?m)^\s*\d{1,3}\s*$\n?', '', body)
        body = re.sub(r'\n{2,}', '\n', body).strip()

        # Keep only what actually reads as a sentence.
        keep = [ln for ln in body.split('\n') if len(ln.strip()) > 40]
        if keep:
            out.append('\n'.join(keep))

    return out


def extract_technical_reports(appendix):
    '''Keep the analysis sections of embedded consultant reports.

    Only the analysis - a report's own appendices, ILI tallies, hardness grids
    and figure logs are many times larger than its findings and would swamp the
    corpus. Vendor equipment manuals share the numbering, so a block must also
    read as metallurgy to qualify.
    '''

    blocks = re.split(r'(?m)\n(?=#{1,3}\s)', appendix)
    kept = []
    for block in blocks:
        heading = block.split('\n', 1)[0]

        if FORM_BULK_HEADING.match(heading):
            continue
        if NAVIGATION_HEADING.match(heading):
            continue
        if STUB_APPENDIX.search(block[:400]):
            continue
        if not (ANALYSIS_HEADING.match(heading) or FINDING_HEADING.match(heading)):
            continue
        if _is_table_block(block):
            continue
        if not METALLURGY_VOCAB.search(block):
            continue

        block = trim_trailing_data(block)
        if len(block.strip()) < 220:
            continue

        kept.append(block.strip())

    return kept


# The PHMSA form family (Dominion, Mid-Valley, Panhandle) splits one report
# across ~60 field-group headings. Each belongs under a template section; merging
# them keeps every field but stops the document chunking as 280-char fragments.
FORM_FIELD_GROUPS = [
    ('System Details', r'(?i)^(?:type of pipeline|gas transmission|hazardous liquid'
                       r'|operator/owner information|pipe failure description'
                       r'|component failure description|upstream (?:pump|compressor) station data'
                       r'|operating pressure|integrity test after failure'
                       r'|soil/water conditions|class location)'),
    ('Investigation Details', r'(?i)^(?:external pipe|internal pipe|cathodic protection'
                              r'|outside force damage|failure isolation|gas migration survey'
                              r'|leak (?:detection|survey)|pressure test|valve)'),
    ('Emergency Response', r'(?i)^(?:failure location|weather conditions'
                           r'|environment sensitivity impact|emergency|notification'
                           r'|evacuation|fire|ignition)'),
    ('Findings and Contributing Factors', r'(?i)^(?:damages|fatalities and injuries'
                                          r'|drug/alcohol testing|countermeasures|lessons learned'
                                          r'|accident chronology|investigation$)'),
]


def merge_form_field_groups(text_content):
    '''Fold the PHMSA form's field-group headings into the template sections.

    Each group's own label is kept inline so no field is lost - "Cathodic
    Protection: P/S (Surface) ..." - while the chunk becomes one coherent
    section instead of twenty stubs.
    '''

    blocks = re.split(r'(?m)\n(?=#{1,3}\s)', text_content)
    if len(blocks) < 20:
        return text_content

    out = []
    buckets = {name: [] for name, _ in FORM_FIELD_GROUPS}

    for block in blocks:
        heading = re.sub(r'^#+\s*', '', block.split('\n', 1)[0]).strip()
        body = (block.split('\n', 1)[1] if '\n' in block else '').strip()

        target = None
        for name, pattern in FORM_FIELD_GROUPS:
            if re.match(pattern, heading):
                target = name
                break

        if target and body:
            buckets[target].append(f'{heading}: {body}')
        elif target:
            continue
        else:
            out.append(block)

    for name, _ in FORM_FIELD_GROUPS:
        if buckets[name]:
            out.append('## ' + name + '\n\n' + '\n'.join(buckets[name]))

    return '\n'.join(out)


# Tables that carry no causal information: photo indexes, agency phone lists,
# FOIA/documentation logs, drug-test results, and the form's signature block.
TABLE_DROP = re.compile(
    r'(?i)^(?:photo\s*no|roll\s*no|agency|name\s*\|?\s*title|preparer|authorized signer'
    r'|appendix\s*\|?\s*documentation|operator:|job function|reason for)'
)

# Tables whose first column is a time or date - an incident chronology.
TIMELINE_HEADER = re.compile(r'(?i)^(?:time|date|matrix of events|time\s*/\s*date)\b')
TIMELINE_CELL = re.compile(r'^\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?$|^\d{1,2}/\d{1,2}/\d{2,4}$')


def _table_rows(block):
    '''Split a markdown table into rows of stripped cells, dropping rule lines.'''

    rows = []
    for line in block:
        if re.match(r'^\s*\|[\s\-:|]+\|?\s*$', line):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if any(cells):
            rows.append(cells)
    return rows


def _dedupe(cells):
    '''Collapse the repeated cells Docling emits for merged/spanning columns.'''

    out = []
    for c in cells:
        if not out or c != out[-1]:
            out.append(c)
    return out


def convert_table(block):
    '''Rewrite a markdown table as prose lines, or drop it.

    A pipe row loses its header when the text is chunked, so "| 10:12 AM | All
    employees accounted for |" becomes an unmoored fragment. Rendering each row
    as a self-labelled line keeps it meaningful on its own.
    '''

    rows = _table_rows(block)
    if not rows:
        return []

    header = _dedupe(rows[0])
    first = header[0] if header else ''

    if TABLE_DROP.match(first):
        return []

    # A chronology: "8:51 a.m. 8/25/08: Gas Control detects a pressure drop."
    # Checked before the label/value branch, since a two-column timeline would
    # otherwise be split into disconnected time and event lines.
    if TIMELINE_HEADER.match(first) or TIMELINE_CELL.match(first):
        body = rows if TIMELINE_CELL.match(first) else rows[1:]
        out = []
        for cells in (_dedupe(r) for r in body):
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            when = ' '.join(cells[:-1])
            out.append(f'{when}: {cells[-1]}')
        return out

    # Two-column label/value blocks (the metadata table, split by page breaks)
    # become the vertical layout parse_document.py's field patterns read.
    if all(len(_dedupe(r)) <= 2 for r in rows):
        out = []
        for cells in (_dedupe(r) for r in rows):
            if len(cells) != 2:
                continue
            label, value = cells
            if label and value and label != value:
                out.append(f'{label}\n\n{value}')
        return out

    # Anything else: label each cell with its column so the row stands alone.
    out = []
    for cells in (_dedupe(r) for r in rows[1:]):
        pairs = [f'{h}: {c}' for h, c in zip(header, cells) if c and h and c != h]
        if pairs:
            out.append('; '.join(pairs) + '.')
    return out


def convert_markdown_tables(text_content):
    '''Replace every markdown table with prose lines.'''

    lines = text_content.split('\n')
    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith('|'):
            j = i
            while j < len(lines) and lines[j].strip().startswith('|'):
                j += 1
            out.extend(convert_table(lines[i:j]))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return '\n'.join(out)


def drop_navigation_sections(text_content):
    '''Remove table-of-contents and figure-list pages from a document body.'''

    blocks = re.split(r'(?m)\n(?=#{1,3}\s)', text_content)
    kept = [b for b in blocks if not NAVIGATION_HEADING.match(b.split('\n', 1)[0])]
    return '\n'.join(kept)


METADATA_LABELS = [
    'Date of Failure', 'Commodity Released', 'City/County & State',
    'City, County, and State', 'OpID & Operator Name', 'Unit # & Unit Name',
    'SMART Activity #', 'Milepost / Location', 'Type of Failure',
    'Fatalities', 'Injuries', 'Description of area impacted', 'Property Damage',
]


def repair_split_metadata_columns(text_content):
    '''Re-pair a metadata table Docling flattened column-by-column.

    Some PDFs extract as every label followed by every value, so "Type of
    Failure" ends up adjacent to "Fatalities" and the parser reads the next
    label as the value. Interleave them back when the counts line up.
    '''

    blocks = re.split(r'(?m)\n(?=## )', text_content)
    out = []
    for block in blocks:
        if not OPERATOR_HEADING.match(block):
            out.append(block)
            continue

        head, _, body = block.partition('\n')
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        def fold(line):
            # OCR turns "OpID" into "OpiD" and the "/" of "Milepost / Location"
            # into a capital I, so drop the characters those confusions involve
            # and compare on what is left.
            return re.sub(r'[^a-z0-9]', '', line.lower()).replace('1', '').replace('l', '').replace('i', '')

        folded_labels = {fold(lab) for lab in METADATA_LABELS}

        def is_label(line):
            return fold(line) in folded_labels

        labels = [l for l in lines if is_label(l)]
        # Already interleaved if labels and values alternate.
        if len(labels) < 4 or len(labels) == len(lines):
            out.append(block)
            continue

        leading = 0
        for line in lines:
            if is_label(line):
                leading += 1
            else:
                break

        values = lines[leading:]
        if leading < 4 or len(values) != leading:
            out.append(block)
            continue

        paired = []
        for label, value in zip(lines[:leading], values):
            paired.append(f'{label}\n\n{value}')
        out.append(head + '\n\n' + '\n\n'.join(paired))

    return '\n'.join(out)


def restore_metadata_spacing(text_content):
    '''Put the blank line back between each label/value pair in the metadata table.

    collapse_intra_section_blanks squeezes the whole section, which leaves the
    next label butted against the previous value. parse_document.py still reads
    it, but the block is unreadable and inconsistent with the rest of the corpus.
    '''

    blocks = re.split(r'(?m)\n(?=## )', text_content)
    out = []
    for block in blocks:
        if not OPERATOR_HEADING.match(block):
            out.append(block)
            continue
        head, _, body = block.partition('\n')
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        out.append(head + '\n\n' + '\n\n'.join(lines))
    return '\n'.join(out)


def drop_blank_form_stubs(text_content):
    '''Drop sections that are only unfilled form labels.

    Docling keeps a form's field names even where the operator entered nothing,
    leaving sections like "Date / NA / Sample Type / Description / Type of Test"
    that carry no information but would each become a chunk.
    '''

    blocks = re.split(r'(?m)\n(?=#{1,3}\s)', text_content)
    kept = []
    for block in blocks:
        head, _, body = block.partition('\n')
        body = body.strip()

        # The metadata table is label/value by design - never a blank stub.
        if re.match(r'(?i)^#{1,3}\s*Operator,?\s*Location', head):
            kept.append(block)
            continue

        if not body:
            if re.match(r'(?i)^#{1,3}\s*(?:photo|figure)\b', head):
                continue
            kept.append(block)
            continue

        if len(body) < 200:
            lines = [l.strip() for l in body.split('\n') if l.strip()]
            # A filled field reads as a sentence or carries digits; a blank form
            # is a stack of short bare labels.
            substantive = [l for l in lines
                           if len(l) > 34 or re.search(r'\d', l) or l.endswith('.')]
            if lines and len(substantive) / len(lines) < 0.34:
                continue

        kept.append(block)

    return '\n'.join(kept)


def drop_repeated_headings(blocks):
    '''Remove blocks whose heading repeats many times - page headers over data.

    Plains carries "## Las Flores to Gaviota" 65 times over its ILI tally.
    '''

    from collections import Counter
    heads = Counter(b.split('\n', 1)[0].strip().lower() for b in blocks)
    return [b for b in blocks if heads[b.split('\n', 1)[0].strip().lower()] <= 5]


def base_clean(text_content):
    '''The shared normalization pass, minus clean_md.py's appendix truncation.'''

    text_content = text_content.replace('&amp;', '&')
    text_content = unicodedata.normalize('NFKC', text_content)
    text_content = text_content.replace('½', '1/2')
    text_content = text_content.replace('¼', '1/4')
    text_content = text_content.replace('¾', '3/4')
    text_content = text_content.replace('…', '...')
    text_content = text_content.replace('²', '2')
    text_content = text_content.replace('›', '>')
    text_content = JUNK_PATTERN.sub('', text_content)
    text_content = re.sub(r'(?im)^\s*<!--\s*image\s*-->\s*$\n?', '', text_content)
    return text_content


# Fields to recover from formats that carry no metadata table, so these files
# can be filtered alongside the rest of the corpus.
SYNTH_FIELDS = [
    ('Date of Failure', [
        r'(?im)^\s*Date\s*(?:&|and)?\s*(?:Time)?\s*of\s*(?:Failure|Accident|Incident)s?\s*:?\s*\n\s*([^\n]+)',
        r'(?i)(?:failure|accident|incident|release|rupture|leak)\s+(?:occurred|happened)\s+on\s+'
        r'((?:January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2},?\s+\d{4})',
        r'(?i)\bon\s+((?:January|February|March|April|May|June|July|August|September|October'
        r'|November|December)\s+\d{1,2},?\s+\d{4})',
    ]),
    ('Commodity Released', [
        r'(?im)^\s*Commodity\s*(?:Released)?\s*:?\s*\n\s*([^\n]+)',
        r'(?i)\b(?:a|the)\s+(crude oil|natural gas|gasoline|diesel|jet fuel|propane|anhydrous ammonia)'
        r'\s+(?:pipeline|leak|release|spill|rupture)',
    ]),
    ('OpID & Operator Name', [
        r'(?im)^\s*Op\s*ID\s*(?:&|and)?\s*Operator\s*Name\s*:?\s*\n\s*([^\n]+)',
        r'(?i)\(\s*Op\s*ID\s*(\d{3,6})\s*\)',
        r'(?im)^\s*Operator\s*:\s*([^\n]+)',
    ]),
    ('Type of Failure', [
        r'(?im)^\s*Type\s*of\s*(?:Failure|Accident)\s*:?\s*\n\s*([^\n]+)',
    ]),
]


def synthesize_metadata_block(raw, body):
    '''Build an Operator/Location table for formats that lack one.

    parse_document.py reads its fields from a vertical "label\\nvalue" block
    inside "## Operator, Location, & Consequences"; without it these documents
    are unfilterable. Only emitted when the document has no such section.
    '''

    if re.search(r'(?i)^##\s*Operator,?\s*Location', body, re.M):
        return None

    lines = []
    for label, patterns in SYNTH_FIELDS:
        for pattern in patterns:
            match = re.search(pattern, raw)
            if match:
                value = ' '.join(match.group(1).split()).strip(' .,;:')
                if value and len(value) < 120:
                    lines.append(f'{label}\n\n{value}')
                break

    if not lines:
        return None

    return '## Operator, Location, & Consequences\n\n' + '\n\n'.join(lines)


def clean_exempt(text_content):

    subject = extract_subject(text_content)
    text_content = base_clean(text_content)

    body, appendix = split_body_and_appendix(text_content)

    body = remove_repeated_page_headers(body)
    body = strip_letterhead_preamble(body)
    body = strip_footer_artifacts(body)
    body = strip_figure_captions(body)
    body = normalize_headings(body)
    body = convert_markdown_tables(body)
    body = drop_navigation_sections(body)
    body = merge_form_field_groups(body)

    metadata_block = synthesize_metadata_block(text_content, body)

    narratives = extract_form_narratives(appendix)
    reports = drop_repeated_headings(extract_technical_reports(appendix))

    parts = []
    if metadata_block:
        parts.append(metadata_block)
    parts.append(body.strip())

    if narratives:
        parts.append('## Narrative Description of Contributing Factors\n\n'
                     + '\n'.join(narratives))

    for report in reports:
        parts.append(report)

    text_content = '\n\n'.join(p for p in parts if p.strip())

    text_content = convert_markdown_tables(text_content)
    text_content = split_sentences(text_content)
    text_content = rejoin_broken_lists(text_content)
    text_content = re.sub(r'[ \t]{2,}', ' ', text_content)
    text_content = collapse_intra_section_blanks(text_content)
    text_content = rejoin_page_break_paragraphs(text_content)
    text_content = drop_blank_form_stubs(text_content)
    text_content = repair_split_metadata_columns(text_content)
    text_content = restore_metadata_spacing(text_content)

    if subject:
        text_content = '# ' + subject + '\n\n' + text_content

    return text_content.strip()


if __name__ == "__main__":
    exempt_dir = "data/md/exempt/"
    cleaned_dir = "data/md_cleaned/"

    response = input('Clean the markdown files in "data/md/exempt/"? (y/n): ')
    if response.lower() != 'y':
        print("Operation cancelled.")
        sys.exit()

    files = [f for f in os.listdir(exempt_dir) if f.endswith(".txt")]

    for filename in sorted(files):
        try:
            with open(os.path.join(exempt_dir, filename), "r", encoding="utf-8") as f:
                raw = f.read()

            cleaned = clean_exempt(raw)

            with open(os.path.join(cleaned_dir, filename), "w", encoding="utf-8") as f:
                f.write(cleaned)

            print(f"[OK] {filename}  {len(raw):>8} -> {len(cleaned):>7}")

        except Exception as e:
            print(f"[ERROR] {filename}: {e}")

    print("Exempt preprocessing complete.")
