"""OCR 适配器模块"""

from .paddle_ocr_adapter import PaddleOCRAdapter, OCRResult, OCRException

__all__ = ["PaddleOCRAdapter", "OCRResult", "OCRException"]
