import io
import logging

try:
    import PyPDF2
except ImportError:
    import pypdf as PyPDF2

logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extracts text content from raw PDF bytes."""
    if not file_bytes:
        raise ValueError("The provided file is empty.")

    try:
        with io.BytesIO(file_bytes) as pdf_stream:
            reader = PyPDF2.PdfReader(pdf_stream)
            
            if len(reader.pages) == 0:
                raise ValueError("The PDF document contains no pages.")
            
            extracted_pages = []
            for page_num, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    extracted_pages.append(page_text.strip())
                else:
                    logger.warning(f"Page {page_num} contained no extractable text.")
            
            full_text = "\n\n".join(extracted_pages).strip()
            
            if not full_text:
                raise ValueError("Could not extract text. The PDF may be scanned or image-only.")
            
            return full_text

    except ValueError as ve:
        raise ve
    except Exception as e:
        logger.error(f"Error during PDF extraction: {str(e)}")
        raise Exception(f"PDF processing failed: {str(e)}")