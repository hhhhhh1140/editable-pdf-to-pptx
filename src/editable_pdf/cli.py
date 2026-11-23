"""Command-line and optional system file-picker entry points."""

import argparse
import json
from pathlib import Path
import sys
from zipfile import BadZipFile

from PIL import UnidentifiedImageError
from pypdfium2 import PdfiumError

from . import __version__
from .converter import FACE, FONT_PATH, convert


def print_page(result):
    print(f"Page {result['page']}: {result['text_boxes']} text boxes, "
          f"{result['shapes']} shapes, {result['pictures']} pictures",flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Rebuild a PDF or slide images as editable PPTX locally.")
    parser.add_argument("inputs",nargs="*",type=Path,metavar="INPUT")
    parser.add_argument("-o","--output",type=Path)
    parser.add_argument("--version",action="version",version=__version__)
    parser.add_argument("--text-mode",choices=("auto","ocr","native"),default="auto",
                        help="Use native PDF text when present, or select OCR explicitly.")
    parser.add_argument("--long-edge",type=int,default=2000,metavar="PIXELS")
    parser.add_argument("--font-file",type=Path,default=FONT_PATH)
    parser.add_argument("--font-name",default=FACE)
    parser.add_argument("--pictures-only-graphics",action="store_true",
                        help="Keep graphic regions as editable picture objects instead of approximating shapes.")
    parser.add_argument("--report",type=Path,help="Write a JSON count of editable objects per slide.")
    parser.add_argument("--overwrite",action="store_true")
    parser.add_argument("--gui",action="store_true",help="Open the system file picker (requires Tk).")
    args=parser.parse_args(argv)
    if args.gui:
        if args.inputs:
            parser.error("--gui opens a file picker and does not accept input paths.")
        return gui()
    if not args.inputs:
        parser.error("Provide a PDF or image path, or use --gui.")
    if not 768<=args.long_edge<=4096:
        parser.error("--long-edge must be between 768 and 4096.")
    inputs=[p.expanduser().resolve() for p in args.inputs]
    output=(args.output or inputs[0].with_suffix(".editable.pptx")).expanduser().resolve()
    report=args.report.expanduser().resolve() if args.report else None
    if output.suffix.lower()!=".pptx":
        parser.error("Choose an output ending in .pptx.")
    if report and (report in inputs or report==output or report.suffix.lower()!=".json"):
        parser.error("--report requires a separate .json path.")
    try:
        stats=convert(inputs,output,long_edge=args.long_edge,mode=args.text_mode,
                      native_graphics=not args.pictures_only_graphics,font_file=args.font_file,
                      font_name=args.font_name,overwrite=args.overwrite,progress=print_page)
        if report:
            report.write_text(json.dumps({"pages":stats},indent=2),encoding="utf-8")
    except (OSError,ValueError,RuntimeError,PdfiumError,UnidentifiedImageError,BadZipFile) as error:
        print(f"Conversion failed: {error}",file=sys.stderr)
        return 1
    print(output)
    return 0


def gui():
    try:
        import tkinter as tk
        from tkinter import filedialog,messagebox
        root=tk.Tk()
    except Exception as error:
        print(f"File picker unavailable ({error}). Run the command with an input path.",file=sys.stderr)
        return 1
    root.withdraw()
    try:
        selected=filedialog.askopenfilename(title="Select a PDF or slide image",
                filetypes=[("PDF or images","*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
                           ("All files","*")])
        if not selected:
            return 0
        source=Path(selected)
        saved=filedialog.asksaveasfilename(title="Save editable PowerPoint",
                initialfile=f"{source.stem}.editable.pptx",defaultextension=".pptx",
                filetypes=[("PowerPoint","*.pptx")])
        if not saved:
            return 0
        output=Path(saved)
        overwrite=output.exists()
        result=main([str(source),"-o",str(output),*(["--overwrite"] if overwrite else [])])
        if result:
            messagebox.showerror("Conversion failed","See the terminal for details.")
        else:
            messagebox.showinfo("Conversion complete",str(output))
        return result
    finally:
        root.destroy()
