"""Recover editable text, graphics, and slide backgrounds."""

from pathlib import Path
from statistics import median
import re
import shutil
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image, ImageFont
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.ns import qn
from pptx.util import Pt

from ._ink import detect_ink
from ._upstream_builder import Builder
from .graphics import graphics
from .input import Recognizer, pages


FONT_PATH=Path(__file__).parent/"assets"/"NotoSansSC-VF.ttf"
FACE="Noto Sans SC"


class DeckBuilder(Builder):
    def add_text(self, slide, element):
        super().add_text(slide,element)
        frame=slide.shapes[-1].text_frame
        frame.auto_size=MSO_AUTO_SIZE.NONE
        frame.word_wrap=False
        for paragraph in frame.paragraphs:
            paragraph.line_spacing=Pt(element["line_step"])

    @staticmethod
    def no_shadow(shape):
        effect=shape._element.find(f"./{qn('p:style')}/{qn('a:effectRef')}")
        if effect is not None:
            effect.set("idx","0")

    def add_shape(self,slide,element):
        super().add_shape(slide,element)
        self.no_shadow(slide.shapes[-1])

    def add_line(self,slide,element):
        super().add_line(slide,element)
        self.no_shadow(slide.shapes[-1])


def load_fonts(path):
    fonts=[]
    for weight in (400,700):
        font=ImageFont.truetype(str(path),100)
        try:
            axes=[a["default"] for a in font.get_variation_axes()]
            if axes:
                axes[0]=weight
                font.set_variation_by_axes(axes)
        except OSError:
            pass
        fonts.append(font)
    return fonts


def read_text(image, lines, box, fonts):
    cleaned=image.copy()
    records=[]
    for line in lines:
        text=re.sub(r"[\x00-\x1f\ufffe\uffff]"," ",line.text).strip()
        x0,y0,x1,y1=line.rect
        if not text or min(x1-x0,y1-y0)<4:
            continue
        x,y,w,h=box(line.rect)
        source_center=y+h/2
        measure=detect_ink(image,line.rect)
        if measure:
            rect,bg,mask,rows,cols,color=measure
            cleaned.paste(Image.fromarray(np.clip(bg,0,255).astype(np.uint8)),
                         rect[:2],Image.fromarray(mask))
            r0,r1=np.percentile(rows,[1,99])
            c0,c1=np.percentile(cols,[.5,99.5])
            source_center=.65*source_center+.35*box((x0,round(rect[1]+(r0+r1)/2),x1,y1))[1]
            density=len(rows)/max(1,(r1-r0+2)*(c1-c0+2))
            ink_height=h*min(1.02,(r1-r0+2)/(y1-y0))
        else:
            ink_height=h*.85
            density=0
            color="222222"
        bold=bool(density>.42 or h>=22)
        font=fonts[bold]
        _,top,_,bottom=font.getbbox(text)
        width_limit=w*100/max(1,font.getlength(text))*.98
        size=min(width_limit,ink_height*100/max(1,bottom-top))
        records.append(dict(text=text,x=x,w=w,center=source_center,
                            size=max(3,size),bold=bold,color="#"+color))
    return sorted(records,key=lambda t:(t["center"],t["x"])), cleaned


def adjacent(above,below):
    sa,sb=above["size"],below["size"]
    distance=below["center"]-above["center"]
    if min(sa,sb)<6 or max(sa,sb)>1.28*min(sa,sb):
        return False
    if not .85*max(sa,sb)<=distance<=1.73*max(sa,sb):
        return False
    if abs(above["x"]-below["x"])>max(3,.34*sa) or min(above["w"],below["w"])<24:
        return False
    if below["text"].startswith(("•","●","▪","■","◦","·")):
        return False
    if above["bold"]!=below["bold"] and (
        len(above["text"])<11 or above["text"].endswith(("：",":","。","!","?"))
    ):
        return False
    ac,bc=(bytes.fromhex(t["color"][1:]) for t in (above,below))
    return sum(abs(a-b) for a,b in zip(ac,bc))<=96


def text_shapes(records, bounds, fonts, face):
    groups=[]
    for record in records:
        eligible=[g for g in groups if adjacent(g[-1],record)]
        if eligible:
            min(eligible,key=lambda g:abs(g[-1]["x"]-record["x"])).append(record)
        else:
            groups.append([record])
    canvas_width,canvas_height=bounds
    for g in groups:
        bold=sum(t["bold"] for t in g)>len(g)/2
        font=fonts[bold]
        limits=[(t["w"]+1.5)*97/max(1,font.getlength(t["text"])) for t in g]
        size=max(3,round(min(median(t["size"] for t in g),*limits),1))
        x=min(t["x"] for t in g)
        w=min(canvas_width-x,max(t["x"]+t["w"] for t in g)-x+2)
        step=(g[-1]["center"]-g[0]["center"])/(len(g)-1) if len(g)>1 else size*1.15
        h=min(canvas_height,size*1.30+step*(len(g)-1))
        y=max(0,min(canvas_height-h,(g[0]["center"]+g[-1]["center"]-h)/2-.6))
        text="\n".join(t["text"] for t in g)
        yield dict(type="text",name=text[:45].replace("\n"," "),text=text,
                   box=[x,y,w,h],size=size,font=face,bold=bold,color=g[0]["color"],
                   align="left",valign="middle",line_step=step)


def convert(inputs,output,*,long_edge=2000,mode="auto",native_graphics=True,
            font_file=FONT_PATH,font_name=FACE,overwrite=False,progress=None):
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}")
    fonts=load_fonts(font_file)
    recognizer=Recognizer()
    slides=[]
    stats=[]
    canvas=None
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix=".editable-pdf-",dir=output.parent) as folder:
        work=Path(folder)
        for i,page in enumerate(pages(inputs,long_edge),1):
            w,h=page.image.size
            if canvas is None:
                scale=960/max(w,h)
                canvas=(w*scale,h*scale)
            cw,ch=canvas
            scale=min(cw/w,ch/h)
            xoff,yoff=(cw-w*scale)/2,(ch-h*scale)/2

            def box(rect):
                x0,y0,x1,y1=rect
                return [x0*scale+xoff,y0*scale+yoff,(x1-x0)*scale,(y1-y0)*scale]

            lines=recognizer.lines(page,mode)
            visible,clean=read_text(page.image,lines,box,fonts)
            assets=work/str(i)
            assets.mkdir()
            background,objects=graphics(clean,box,assets,native_graphics)
            texts=list(text_shapes(visible,canvas,fonts,font_name))
            slides.append(dict(background=background,elements=[*objects,*texts]))
            stats.append(dict(page=i,text_boxes=len(texts),
                              shapes=sum(o["type"] in ("shape","line") for o in objects),
                              pictures=sum(o["type"]=="image" for o in objects)))
            if progress:
                progress(stats[-1])
        if not slides:
            raise ValueError("The input did not contain any pages.")
        cw,ch=canvas
        layout=dict(source_width=cw,source_height=ch,
                    slide_size=dict(width_in=cw/72,height_in=ch/72),slides=slides)
        draft=work/"result.pptx"
        DeckBuilder(layout,draft,work).build()
        if overwrite:
            draft.replace(output)
        else:
            with output.open("xb") as target,draft.open("rb") as source:
                try:
                    shutil.copyfileobj(source,target)
                except BaseException:
                    target.close()
                    output.unlink()
                    raise
    return stats
