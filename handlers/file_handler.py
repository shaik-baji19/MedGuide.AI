import logging
from werkzeug.utils import secure_filename
from .pdf_handler import extract_text_from_pdf

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'pdf', 'txt', 'docx'}

def allowed_file(filename: str) -> bool:
    """Checks if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_file(file) -> dict:
    """
    Validates uploaded files and routes PDFs to pdf_handler.py.
    """
    if not file or file.filename == '':
        raise ValueError("No file selected for upload.")

    if not allowed_file(file.filename):
        raise ValueError("Unsupported file format.")

    filename = secure_filename(file.filename)
    file_bytes = file.read()

    if filename.lower().endswith('.pdf'):
        text = extract_text_from_pdf(file_bytes)
        return {
            "filename": filename,
            "text": text,
            "status": "success"
        }

    raise ValueError("File format not currently supported by handlers.")

# Alias so both function names work seamlessly across app.py and handlers/__init__.py
process_uploaded_file = process_file