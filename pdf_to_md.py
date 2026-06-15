from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption
import os
import shutil

def extract_structured_text(pdf_path, filename):
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.FAST

    converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(pdf_path)
    markdown_output = result.document.export_to_markdown()
    filename = filename.replace(".pdf", "")
    output_path = "Replace with your path"
    processed_pdf_dir = "Replace with your path"

    os.makedirs(processed_pdf_dir, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(markdown_output)

    shutil.move(pdf_path, os.path.join(processed_pdf_dir, filename))


pdfdir = "Replace with path to pdf files"
for filename in os.listdir(pdfdir):
    if filename.endswith(".pdf"):
        pdf_path = os.path.join(pdfdir, filename)
        extract_structured_text(pdf_path, filename)
