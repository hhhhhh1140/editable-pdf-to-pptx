# Third-party components

- [EditableImage2PPTSkill](https://github.com/soulmujoco/EditableImage2PPTSkill), commit `741a279e99da3b6818aa4c06f4ce8f151f1443ce`. The original MIT-licensed builder is vendored as `src/editable_pdf/_upstream_builder.py`. Its original [license](LICENSE-EditableImage2PPTSkill.txt) is included.
- [Noto Sans SC](https://github.com/notofonts/noto-cjk), version 2.004, original variable TrueType file from commit `523d033d6cb47f4a80c58a35753646f5c3608a78`. The SIL Open Font License is in `src/editable_pdf/assets/OFL-NotoSansSC.txt`.
- Runtime dependencies are installed separately by pip. [RapidOCR](https://github.com/RapidAI/RapidOCR) supplies the OCR models and [ONNX Runtime](https://github.com/microsoft/onnxruntime) runs inference. PDF rendering and export use [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) and [python-pptx](https://github.com/scanny/python-pptx). See each dependency for its own terms.
