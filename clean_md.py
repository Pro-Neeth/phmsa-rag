import re
import os
import unicodedata
import sys
from collections import Counter


''' Cleans up the formatting of a given text document '''


# Files cleaned by hand. The __main__ loop skips these unless --force is passed,
# so a rerun can never overwrite manual work. Derived by inspection, not mtime:
# some hand-cleaned files have older mtimes than untouched ones.
PROTECTED = frozenset({
    "122652marathonashmoreil20080903.pdf.txt",
    "130748_Northern_Natural_Gas_2016_08_10_Final.pdf.txt",
    "130804_Enbridge_Cass_Lake_MN_2010_07_28_Final.pdf.txt",
    "133678_FIR_TGP_Cumberland_OH_2011_03_01_Final.txt",
    "139107_Williams_Gas_Pipeline_North_Bergen_NJ.pdf.txt",
    "140298_Buckeye_1845_Failure_Investigation.pdf.txt",
    "144161-Magellan-Pipeline-Company-FIR-Redacted.pdf.txt",
    "144352 FIR Enterprise Erie_IL_2013_08_13.pdf.txt",
    "147517magellan20121125.pdf.txt",
    "147585buckeyelindenfailureinvestigationreport2.pdf.txt",
    "149469enterpriseproductsoperatingllcfir2015126.pdf.txt",
    "150663_Transcontinental_Unityville_PA_June_9.pdf.txt",
    "151195_Kiantone_West_Seneca_NY_Aug_25_2015.pdf.txt",
    "20221207_TC Oil Pipeline Operations.pdf.txt",
    "AmocoBPflange_red_app_d.txt",
    "BP_Oil_Cincinnati_Ohio_022504.txt",
    "Bridger Lake HL WY 2010-04-02 508.pdf.txt",
    "Buckeye HL NY 2011-09-20.pdf.txt",
    "Buckeye HL PA 2009-12-29.pdf.txt",
    "Buckeye_HL_PA_20110320.pdf.txt",
    "CGT GT PA 2011-11-03 508.pdf.txt",
    "CGT GT PA 508 2008-11-5_0.pdf.txt",
    "bellefourchewrightwy20111113redacted.pdf.txt",
    "centurionpipelinelptankmixer20150802.pdf.txt",
})


# Junk/private-use/invisible characters left by the PDF extraction:
#   U+E000-U+F8FF  - Private Use Area: Wingdings/Symbol bullet artifacts
#                     left by PDF font encoding (f0b7, f020, f02d, f0a7, ...)
#   U+FFFD          - replacement character (failed decode)
#   U+00AD          - soft hyphen (invisible)
#   U+1D40, U+1D39  - garbled modifier letter superscripts
#   U+200B-U+200F   - zero-width spaces / joiners / marks
#   U+202A-U+202E   - directional formatting characters
#   U+FEFF          - BOM / zero-width no-break space
JUNK_PATTERN = re.compile(
    r'[\ue000-\uf8ff\ufffd\u00ad\u1d40\u1d39'
    r'\u200b-\u200f\u202a-\u202e\ufeff]'
)


# Section names that belong to the PHMSA FIR template. Used to tell a real
# section heading apart from a repeated page-header title.
CANONICAL_HEADING = re.compile(
    r'(?i)^\s*(?:operator|executive\s+summary|summary|system\s+(?:details|description)'
    r'|events?\s+leading|emergency\s+response|investigation|metallurgical|mechanical'
    r'|findings?|conclusions?|pipe\s+specifications?|background|analysis'
    r'|recommendations?|corrective\s+actions?|overpressure|pipe\s+repair)'
)

# The letterhead block that opens most reports, one label per line.
LETTERHEAD_MARKER = re.compile(
    r'(?im)US Department of Transportation|Pipelines? and Hazardous Materials'
    r'|Office of Pipeline Safety|Principal Investigator|Senior Accident Investigator'
    r'|Region(?:al)? Director|Date of Report|^\s*(?:DOT|OPS|PHMSA|USDOT)\s*$'
)

# Page-header repeats of the report title, e.g.
# "## Failure Investigation Report - Buckeye Tank 230 Leak".
PAGE_HEADER_TITLE = re.compile(
    r'(?im)^[#\s]*(?:Failure Investigation Report|Incident Report|Accident Report)\b.*$\n?'
)

# Page footers left behind between sections.
FOOTER_ARTIFACT = re.compile(
    r'(?im)^[#\s]*\[?\s*Failure Date\s*:?\s*\d{1,2}/\d{1,2}/\d{2,4}\s*\]?\s*$\n?'
    r'|^\s*\d+\s+All times are .*?noted\.?\s*$\n?'
    r'|^\s*Page \d+(?: of \d+)?\s*$\n?'
    r'|^##\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$\n?'
)

# A figure/photo caption line. These label an image the text does not contain,
# so on their own they are dead weight in a chunk.
FIGURE_CAPTION = re.compile(
    r'(?im)^\s*(?:figure|photo|fig\.)\s*\d+\s*[-:.]?\s*\S.*$\n?'
)

# ... but a sentence that merely mentions a figure ("Figure 2 is a post-incident
# view of the ROW, which is in Union Parish") carries real context, so it stays.
CAPTION_IS_PROSE = re.compile(
    r'(?i)\b(?:provides?|shows?|is|was|are|were|depicts?|illustrates?'
    r'|indicates?|presents?|can be seen)\b'
)

# A "Source: http://..." credit line under a figure.
FIGURE_SOURCE = re.compile(r'(?im)^\s*source\s*:\s*\S.*$\n?')

# A list enumerator at the start of a line: "1.", "- a.", "iv.".
ENUMERATOR = r'(?:-\s*)?(?:\d{1,2}|[a-z]|[ivx]{1,4})\.'

# Stand-in for the dot in an enumerator while sentences are being split, so the
# splitter cannot break "1. New ring installed" across two lines.
_DOT_SENTINEL = '\x00'

OPERATOR_HEADING = re.compile(r'(?i)^##\s*Operator,?\s*Location')
SUMMARY_HEADING = re.compile(r'(?i)^##\s*(?:executive\s+summary|summary)\b')


def extract_subject(text_content):
    '''Pull the report title out of the letterhead before it gets stripped.

    parse_document.py reads this into its "Subject" metadata field, so it has to
    survive the preamble removal. Three tiers, because Docling does not lay the
    letterhead out consistently.
    '''

    # Title directly under the "Subject" label.
    match = re.search(
        r'(?im)^Subject:?\s*\n+\s*((?:Failure|Incident|Accident)\b.+)', text_content
    )
    if match:
        return match.group(1).strip()

    # Docling sometimes interleaves investigator names and dates between the
    # label and the title, so scan the lines that follow it.
    match = re.search(r'(?ims)^Subject:?\s*\n(.{0,600}?)(?=^##|\Z)', text_content)
    if match:
        for line in match.group(1).split('\n'):
            line = line.strip()
            if (len(line) > 25
                    and re.search(r'(?i)failure|incident|accident|pipe ?line|rupture|release', line)
                    and not re.match(r'(?i)^(?:opid|unit|date|nrc|odes)', line)):
                return line

    # No usable label — fall back to a title-shaped heading.
    match = re.search(r'(?m)^##\s*((?:Failure|Incident|Accident)\b.+)', text_content)
    if match:
        return match.group(1).strip()

    return None


def strip_letterhead_preamble(text_content):
    '''Drop the DOT/PHMSA cover block preceding the first section heading.

    Only fires when the text above the heading actually looks like a letterhead;
    a few reports open directly on real content.
    '''

    match = re.search(r'(?m)^## ', text_content)
    if not match:
        return text_content

    preamble = text_content[:match.start()]
    if preamble.strip() and LETTERHEAD_MARKER.search(preamble):
        return text_content[match.start():]

    return text_content


# Same section names as CANONICAL_HEADING, matched against the squashed form
# produced by _normalize_heading (no spaces or punctuation).
CANONICAL_HEADING_NORMALIZED = re.compile(
    r'^(?:operator|executivesummary|summary|system(?:details|description)'
    r'|events?leading|emergencyresponse|investigation|metallurgical|mechanical'
    r'|findings?|conclusions?|pipespecifications?|background|analysis'
    r'|recommendations?|correctiveactions?|overpressure|piperepair)'
)


def _normalize_heading(heading):
    '''Reduce a heading to letters and digits so spacing/punctuation noise
    between page-header repeats does not defeat the comparison.'''

    return re.sub(r'[^a-z0-9]+', '', heading.lower())


def remove_repeated_page_headers(text_content):
    '''Remove the report title repeated as a page header on every page.

    Keeps one occurrence if the document has no other heading to fall back on.
    '''

    headings = re.findall(r'(?m)^##+ .*$', text_content)
    canonical = [h for h in headings if CANONICAL_HEADING.match(re.sub(r'^#+\s*', '', h))]

    stripped = PAGE_HEADER_TITLE.sub('', text_content)

    # Docling often breaks a long title across lines, so the tail survives as its
    # own heading ("Material Failure, Girth Weld"). Any non-template heading that
    # appears more than once is a page header, whatever it says.
    counts = Counter(
        _normalize_heading(h) for h in re.findall(r'(?m)^##+ (.*)$', stripped)
    )
    repeated = {
        key for key, n in counts.items()
        if n > 1 and key and not CANONICAL_HEADING_NORMALIZED.match(key)
    }
    if repeated:
        stripped = '\n'.join(
            line for line in stripped.split('\n')
            if not (line.startswith('##')
                    and _normalize_heading(re.sub(r'^#+\s*', '', line)) in repeated)
        )

    if not canonical and not re.search(r'(?m)^## ', stripped):
        first = PAGE_HEADER_TITLE.search(text_content)
        if first:
            return first.group(0).strip() + '\n\n' + stripped.lstrip()

    return stripped


def strip_footer_artifacts(text_content):
    '''Remove page footers and footnote definitions stranded between sections.'''

    return FOOTER_ARTIFACT.sub('', text_content)


def strip_figure_captions(text_content):
    '''Drop caption lines that only label an image.

    The images themselves never survive the PDF extraction, so "Figure 3 Failed
    Hose" retrieves nothing useful and dilutes the chunk it sits in. A line that
    reads as a sentence about the figure is kept - it describes the scene in
    words, which is exactly the context a retrieval answer can use.
    '''

    def drop(match):
        line = match.group(0)
        return line if CAPTION_IS_PROSE.search(line) else ''

    text_content = FIGURE_CAPTION.sub(drop, text_content)
    return FIGURE_SOURCE.sub('', text_content)


def rejoin_broken_lists(text_content):
    '''Pull a list item back onto the line with its enumerator.

    Cleans up "1.\\nNew ring installed" left by an earlier sentence split.
    '''

    return re.sub(
        r'(?m)^(\s*' + ENUMERATOR + r')\s*\n+(?=\S)',
        r'\1 ',
        text_content
    )


def split_sentences(text_content):
    '''Put each sentence on its own line for readability.

    Enumerator dots are masked first so "1. New ring" is never treated as a
    sentence boundary.
    '''

    text_content = re.sub(
        r'(?m)^(\s*(?:-\s*)?(?:\d{1,2}|[a-z]|[ivx]{1,4}))\.(\s)',
        r'\1' + _DOT_SENTINEL + r'\2',
        text_content
    )

    # Pattern 1: 2+ spaces after .!? then capital — dominant PDF extraction artifact.
    text_content = re.sub(r'([.!?])\s{2,}(?=[A-Z])', r'\1\n', text_content)
    # Pattern 2: single space, but only when preceded by lowercase/digit/closing bracket
    # (rules out abbreviations like LLC., a.m., p.m., No.) and followed by TitleCase
    # (rules out numbers and ALL-CAPS words).
    text_content = re.sub(r'(?<=[a-z0-9\)\]])\.\s(?=[A-Z][a-z])', '.\n', text_content)

    return text_content.replace(_DOT_SENTINEL, '.')


def _split_sections(text_content):
    '''Split into [preamble, section, section, ...] on ## headings.'''

    return re.split(r'(?m)\n(?=## )', text_content)


def rejoin_page_break_paragraphs(text_content):
    '''Rejoin a sentence that a page header split in two.

    Removing the header leaves "...placement of these" directly above "tubes
    displaced...". Skips the metadata table, whose label/value lines are
    separate by design.
    '''

    out = []
    for block in _split_sections(text_content):
        if OPERATOR_HEADING.match(block):
            out.append(block)
            continue

        lines = block.split('\n')
        merged = []
        for line in lines:
            if (merged
                    and merged[-1].strip()
                    and re.search(r'[a-z,]$', merged[-1].rstrip())
                    and re.match(r'^[a-z]', line.strip())
                    and not re.match(r'^\s*' + ENUMERATOR, line)
                    and not merged[-1].lstrip().startswith('#')):
                merged[-1] = merged[-1].rstrip() + ' ' + line.strip()
            else:
                merged.append(line)
        out.append('\n'.join(merged))

    return '\n'.join(out)


def collapse_intra_section_blanks(text_content):
    '''Make each section body a contiguous run of lines.

    One blank line stays between the heading and the body and between sections.
    The metadata table keeps its blank lines: parse_document.py's field
    patterns are keyed to that vertical label/value layout.
    '''

    out = []
    for block in _split_sections(text_content):
        if not block.strip():
            continue

        if OPERATOR_HEADING.match(block):
            out.append(block.strip())
            continue

        lines = block.split('\n')
        if lines[0].startswith('##'):
            heading, body = lines[0].strip(), lines[1:]
        else:
            heading, body = None, lines

        body = [line.rstrip() for line in body if line.strip()]
        if not body:
            out.append(heading or '')
            continue

        out.append((heading + '\n\n' if heading else '') + '\n'.join(body))

    return '\n\n'.join(b for b in out if b)


def reorder_summary_after_table(text_content):
    '''Move a summary that precedes the metadata table to just after it.'''

    blocks = _split_sections(text_content)

    operator_idx = next((i for i, b in enumerate(blocks) if OPERATOR_HEADING.match(b)), None)
    summary_idx = next((i for i, b in enumerate(blocks) if SUMMARY_HEADING.match(b)), None)

    if operator_idx is None or summary_idx is None or summary_idx > operator_idx:
        return text_content

    summary = blocks.pop(summary_idx)
    blocks.insert(operator_idx, summary)

    return '\n'.join(blocks)


def strip_footnote_refs(text_content):
    '''Drop a footnote marker left inline after a timezone abbreviation.

    Deliberately narrow: it only fires after an all-caps abbreviation such as
    "(CST) 1 ,". A general "digit between a letter and a comma" rule looks
    tempting but eats real data - it would turn "December 7, 2022" into
    "December, 2022" and "1,158 psig" into "1158 psig".
    '''

    return re.sub(r'(?<=\))\s+\d\s*(?=,)', '', text_content)


def clean(text_content):

    # Capture the title before the letterhead carrying it is removed.
    subject = extract_subject(text_content)

    # Remove everything from the first ## Appendix(es) section onwards
    text_content = re.split(r'(?im)^## APPE', text_content)[0]

    # Replace markdown ampersands with real ampersands
    text_content = text_content.replace('&amp;', '&')

    # Normalize unicode (NFKC handles ligatures, fullwidth chars, etc.)
    text_content = unicodedata.normalize('NFKC', text_content)

    # Normalize vulgar fractions and common symbol substitutions
    text_content = text_content.replace('\u00bd', '1/2')   # ½
    text_content = text_content.replace('\u00bc', '1/4')   # ¼
    text_content = text_content.replace('\u00be', '3/4')   # ¾
    text_content = text_content.replace('\u2026', '...')   # …
    text_content = text_content.replace('\u00b2', '2')     # ² (superscript)
    text_content = text_content.replace('\u203a', '>')     # › (angle quote)

    text_content = JUNK_PATTERN.sub('', text_content)

    # Remove Docling image placeholder lines (e.g. "<!-- image -->")
    text_content = re.sub(r'(?im)^\s*<!--\s*image\s*-->\s*$\n?', '', text_content)

    # Headers first: some reports open with the title heading, which would
    # otherwise hide the letterhead behind it and leave an empty preamble.
    text_content = remove_repeated_page_headers(text_content)
    text_content = strip_letterhead_preamble(text_content)
    text_content = strip_footer_artifacts(text_content)
    text_content = strip_figure_captions(text_content)

    text_content = split_sentences(text_content)
    text_content = rejoin_broken_lists(text_content)

    # Collapse runs of spaces left by the PDF's justified text.
    text_content = re.sub(r'[ \t]{2,}', ' ', text_content)

    text_content = strip_footnote_refs(text_content)
    # Collapse first, so a sentence split across a page break sits on adjacent
    # lines by the time the rejoin runs.
    text_content = collapse_intra_section_blanks(text_content)
    text_content = rejoin_page_break_paragraphs(text_content)
    text_content = reorder_summary_after_table(text_content)

    if subject:
        text_content = '# ' + subject + '\n\n' + text_content

    return text_content.strip()



if __name__ == "__main__":
    md_dir   = "data/md/"
    cleaned_dir = "data/md_cleaned/"

    force = "--force" in sys.argv

    response = input('Do you want to clean the markdown files in the "data/md/" directory? (y/n): ')
    if response.lower() != 'y':
        print("Operation cancelled.")
        sys.exit()

    os.makedirs(cleaned_dir, exist_ok=True)

    files = [f for f in os.listdir(md_dir) if f.endswith(".txt")]

    if not files:
        print(f"No .txt files found in {md_dir}")
    else:
        for filename in files:
            raw_path     = os.path.join(md_dir, filename)
            cleaned_path = os.path.join(cleaned_dir, filename)

            if filename in PROTECTED and not force:
                print(f"[SKIP protected] {filename}")
                continue

            try:
                with open(raw_path, "r", encoding="utf-8") as f:
                    text_content = f.read()

                cleaned = clean(text_content)

                with open(cleaned_path, "w", encoding="utf-8") as f:
                    f.write(cleaned)

                print(f"[OK] {filename}")

            except Exception as e:
                print(f"[ERROR] {filename}: {e}")

        print("Preprocessing complete.")
