"""Stream PDF/image pages and read native and recognized text positions."""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, ImageSequence
import pypdfium2 as pdfium


LOG = logging.getLogger(__name__)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


@dataclass
class Line:
    text: str
    rect: tuple[int, int, int, int]
    confidence: float = 1.0


@dataclass
class Page:
    image: Image.Image
    text: list[Line]
    needs_ocr: bool


def native_lines(page, bitmap):
    """Map visible PDF text boxes through the same transform as page rendering."""
    conv = bitmap.get_posconv(page)
    with closing(page.get_textpage()) as text_page:
        lines = []
        characters = []
        boxes = []

        def save():
            text = "".join(characters).strip()
            if not text or not boxes:
                return
            x0 = max(0, min(b[0] for b in boxes))
            y0 = max(0, min(b[1] for b in boxes))
            x1 = min(bitmap.width, max(b[2] for b in boxes))
            y1 = min(bitmap.height, max(b[3] for b in boxes))
            if x1>x0 and y1>y0:
                lines.append(Line(text, (x0,y0,x1,y1)))

        for i in range(text_page.count_chars()):
            text = text_page.get_text_range(i,1)
            if not text:
                continue
            if "\r" in text or "\n" in text:
                save()
                characters.clear()
                boxes.clear()
                continue
            if text.isspace():
                if characters:
                    characters.append(" ")
                continue
            left,bottom,right,top = text_page.get_charbox(i)
            x0,y0 = conv.to_bitmap(left,top)
            x1,y1 = conv.to_bitmap(right,bottom)
            if boxes and (abs(y0-boxes[-1][1]) > max(12, abs(y1-y0)*.85)
                          or x0 < boxes[-1][0]-10 or x0-boxes[-1][2]>max(20,abs(y1-y0)*1.8)):
                save()
                characters.clear()
                boxes.clear()
            characters.append(text)
            boxes.append((min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1)))
        save()
        return lines


def pages(paths: list[Path], long_edge: int) -> Iterator[Page]:
    for path in paths:
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            with Image.open(path) as opened:
                for frame in ImageSequence.Iterator(opened):
                    image = ImageOps.exif_transpose(frame).convert("RGBA")
                    base = Image.new("RGBA",image.size,"white")
                    base.alpha_composite(image)
                    base.thumbnail((long_edge,long_edge),Image.Resampling.LANCZOS)
                    yield Page(base.convert("RGB"), [], True)
            continue
        if path.suffix.lower()!=".pdf":
            raise ValueError(f"Unsupported input type: {path.name}")
        with pdfium.PdfDocument(path) as pdf:
            for page in pdf:
                with closing(page):
                    pw,ph=page.get_size()
                    with closing(page.render(scale=long_edge/max(pw,ph))) as bitmap:
                        image=bitmap.to_pil().convert("RGB")
                        try:
                            text=native_lines(page,bitmap)
                        except (pdfium.PdfiumError,ValueError,RuntimeError):
                            LOG.warning("Native text extraction failed; using OCR for this page.")
                            text=[]
                        # Images on an otherwise vector slide can also contain labels.
                        has_image=any(o.type==3 for o in page.get_objects())
                        yield Page(image,text,not text or has_image)


def intersection(a, b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def area(rect):
    return (rect[2]-rect[0])*(rect[3]-rect[1])


class Recognizer:
    def __init__(self):
        self.engine=None

    def lines(self,page,mode):
        if mode=="native" or (mode=="auto" and not page.needs_ocr):
            return page.text
        if self.engine is None:
            import onnxruntime
            from rapidocr import RapidOCR
            onnxruntime.disable_telemetry_events()
            self.engine=RapidOCR(params={
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            })
        data=cv2.cvtColor(np.asarray(page.image),cv2.COLOR_RGB2BGR)
        result=self.engine(data)
        if result.boxes is None:
            return page.text if mode=="auto" else []
        lines=list(page.text if mode=="auto" else [])
        width,height=page.image.size
        for quad,text,confidence in zip(result.boxes,result.txts,result.scores,strict=True):
            left,top=map(int,np.floor(quad.min(axis=0)))
            right,bottom=map(int,np.ceil(quad.max(axis=0)))
            rect=(max(0,left),max(0,top),min(width,right),min(height,bottom))
            if area(rect)<=0:
                continue
            if mode=="auto" and any(intersection(rect,n.rect)>=area(rect)*.48 for n in page.text):
                continue
            lines.append(Line(text,rect,float(confidence)))
        return lines
