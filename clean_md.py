import re
import os
import unicodedata


''' Cleans up the formatting of a given text document '''

def clean(text_content):

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

    # Strip junk/private-use/invisible characters:
    #   U+F0B7, U+F0BE  - Wingdings private-use bullet artifacts
    #   U+FFFD          - replacement character (failed decode)
    #   U+00AD          - soft hyphen (invisible)
    #   U+1D40, U+1D39  - garbled modifier letter superscripts
    #   U+200B-U+200F   - zero-width spaces / joiners / marks
    #   U+202A-U+202E   - directional formatting characters
    #   U+FEFF          - BOM / zero-width no-break space
    JUNK_CHARS = re.compile(
        r'[\uf0b7\uf0be\ufffd\u00ad\u1d40\u1d39'
        r'\u200b-\u200f\u202a-\u202e\ufeff]'
    )
    text_content = JUNK_CHARS.sub('', text_content)

    # Extract the subject title (line immediately after "Subject" label) and
    # remove all repeated page-header occurrences of it throughout the document.
    # e.g. "## Failure Investigation Report -Marathon Pipe Line LLC -Material Failure, Rupture Failure Date ..."
    subject_match = re.search(r'(?m)^Subject\s*\n+\s*(Failure.+)', text_content)
    if subject_match:
        subject_title = subject_match.group(1).strip()
        # Take the first 6 words (letters only) — enough to be distinctive
        words = re.findall(r'[A-Za-z]+', subject_title)[:6]
        # Allow any mix of spaces and dashes between words to handle formatting variation
        flexible_pattern = r'[\s\-]+'.join(re.escape(w) for w in words)
        # Remove any line that begins with optional ## markers and matches the pattern
        text_content = re.sub(
            r'(?im)^[#\s]*' + flexible_pattern + r'.*$\n?',
            '',
            text_content
        )

    # Put each sentence on its own line for readability.
    # Pattern 1: 2+ spaces after .!? then capital — dominant PDF extraction artifact.
    text_content = re.sub(r'([.!?])\s{2,}(?=[A-Z])', r'\1\n', text_content)
    # Pattern 2: single space, but only when preceded by lowercase/digit/closing bracket
    # (rules out abbreviations like LLC., a.m., p.m., No.) and followed by TitleCase
    # (rules out numbers and ALL-CAPS words).
    text_content = re.sub(r'(?<=[a-z0-9\)\]])\.\s(?=[A-Z][a-z])', '.\n', text_content)

    return text_content.strip()



if __name__ == "__main__":
    md_dir   = "data/md/"
    cleaned_dir = "data/md_cleaned/"

    os.makedirs(cleaned_dir, exist_ok=True)

    files = [f for f in os.listdir(md_dir) if f.endswith(".txt")]

    if not files:
        print(f"No .txt files found in {md_dir}")
    else:
        for filename in files:
            raw_path     = os.path.join(md_dir, filename)
            cleaned_path = os.path.join(cleaned_dir, filename)

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
