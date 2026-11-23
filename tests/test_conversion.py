import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from editable_pdf.cli import main
from editable_pdf.converter import FONT_PATH


NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def native_fixture(path):
    """Write a one-page digital PDF containing actual selectable text."""
    stream=(b"0.08 0.35 0.65 rg 60 265 510 50 re f\n"
            b"1 1 1 rg BT /F1 24 Tf 85 282 Td (Project Overview) Tj ET\n")
    objects=[
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 640 360] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode()+stream+b"endstream",
    ]
    data=bytearray(b"%PDF-1.4\n")
    offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data))
        data+=f"{i} 0 obj\n".encode()+obj+b"\nendobj\n"
    location=len(data)
    data+=f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for pos in offsets[1:]:
        data+=f"{pos:010d} 00000 n \n".encode()
    data+=f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{location}\n%%EOF\n".encode()
    path.write_bytes(data)


def raster_fixture(path):
    """Make a mixed slide with text, two panels and a textured illustration."""
    image=Image.new("RGB",(1248,700),"white")
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((58,63,1192,183),radius=16,fill="#1266B5")
    draw.rounded_rectangle((60,228,560,597),radius=20,fill="#E3F1FA",outline="#438BC0",width=3)
    face=ImageFont.truetype(str(FONT_PATH),55)
    draw.text((87,88),"中文测试 PowerPoint",font=face,fill="white")
    heading=ImageFont.truetype(str(FONT_PATH),36)
    heading.set_variation_by_axes([700])
    draw.text((58,9),"年度建设规划：从数据管理到可持续的业务协作与智能系统集成",
              font=heading,fill="#101828")
    draw.text((89,305),"Editable text 42",font=ImageFont.truetype(str(FONT_PATH),32),fill="#102240")
    yy,xx=np.indices((220,290))
    gradient=np.stack((40+(xx+yy)%103,75+xx%160,120+yy%120),axis=2).astype(np.uint8)
    mask=Image.new("L",(290,220))
    ImageDraw.Draw(mask).ellipse((2,2,288,218),fill=255)
    image.paste(Image.fromarray(gradient),(702,265),mask)
    image.save(path)


class ConversionTest(unittest.TestCase):
    def test_native_pdf_and_ocr_image_share_editable_deck(self):
        with TemporaryDirectory() as parent:
            folder=Path(parent)
            pdf=folder/"native.pdf"
            image=folder/"幻灯片.png"
            output=folder/"试验稿.pptx"
            report=folder/"objects.json"
            native_fixture(pdf)
            raster_fixture(image)
            self.assertEqual(main([str(pdf),str(image),"-o",str(output),
                                   "--report",str(report)]),0)
            with ZipFile(output) as pptx:
                self.assertIsNone(pptx.testzip())
                self.assertNotIn("ppt/slides/slide3.xml",pptx.namelist())
                one,two=(ET.fromstring(pptx.read(f"ppt/slides/slide{i}.xml"))
                         for i in (1,2))
                self.assertIn("Project Overview",
                              " ".join(n.text or "" for n in one.findall(".//a:t",NS)))
                text="".join(n.text or "" for n in two.findall(".//a:t",NS))
                self.assertIn("中文测试",text)
                self.assertIn("智能系统集成",text)
                self.assertIn("42",text)
                self.assertTrue(two.findall(".//p:pic",NS))
                self.assertIsNotNone(two.find(".//p:bg/p:bgPr/a:solidFill",NS))
                self.assertTrue(two.findall(".//p:sp/p:spPr/a:prstGeom",NS))
            counts=json.loads(report.read_text())["pages"]
            self.assertGreaterEqual(counts[1]["shapes"],1)
            self.assertGreaterEqual(counts[1]["pictures"],1)
            self.assertEqual(main([str(pdf),"-o",str(output)]),1)

    def test_scan_pdf_uses_ocr(self):
        with TemporaryDirectory() as parent:
            folder=Path(parent)
            image=folder/"sample.png"
            pdf=folder/"scan.pdf"
            output=folder/"editable.pptx"
            raster_fixture(image)
            with Image.open(image) as raster:
                raster.save(pdf,"PDF")
            self.assertEqual(main([str(pdf),"-o",str(output)]),0)
            with ZipFile(output) as pptx:
                root=ET.fromstring(pptx.read("ppt/slides/slide1.xml"))
            self.assertIn("中文测试","".join(n.text or "" for n in root.findall(".//a:t",NS)))


if __name__ == "__main__":
    unittest.main()
