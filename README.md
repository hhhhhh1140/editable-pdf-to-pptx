# Editable PDF to PPTX

把 PDF、扫描件和幻灯片截图重建为可编辑的 PowerPoint 文件。支持 **Windows、macOS、Linux** 上的 Python 3.11–3.13（64 位）。转换在本地 CPU 上运行，默认识别中英文。

- PDF 文字层可直接读取。图片文字通过 RapidOCR 和 ONNX Runtime 识别。
- 同一文本框统一字体和字号，文字保持可选中和编辑。
- 自动识别简单色块、卡片边框、圆形和分隔线。复杂插画和照片作为可移动、裁剪和替换的独立图片。
- 支持多个 PDF 或图片合成一份 PPTX，保持输入顺序。

## 安装

下载或克隆此仓库，在项目目录运行。推荐用 Python 3.12 的虚拟环境。

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m editable_pdf "source.pdf" -o "editable.pptx"
```

macOS 和 Linux：

```bash
.venv/bin/python -m pip install .
.venv/bin/python -m editable_pdf "source.pdf" -o "editable.pptx"
```

如果 Python 的命令是 `py -3.12` 或 `python3`，用它创建虚拟环境。首次安装需要下载依赖。安装后可以离线转换。GitHub 主机常见架构的安装验证见 [Actions](../../actions)。

## 用法

激活虚拟环境后可以使用命令 `pdf-to-pptx`，也可以继续使用 `python -m editable_pdf`。

```text
pdf-to-pptx source.pdf -o editable.pptx
pdf-to-pptx slide1.png slide2.jpg -o images.pptx
pdf-to-pptx source.pdf --text-mode ocr --long-edge 2600 --report objects.json
pdf-to-pptx --gui
```

- `--text-mode auto` 是默认值。可用 `ocr` 强制识别可见画面，或用 `native` 只提取 PDF 文字层。
- `--gui` 需要 Python 附带 Tk。没有 Tk 也能直接运行命令行。
- `--pictures-only-graphics` 把识别出的图形保留成分离图片，适合复杂插画或希望减少原生几何近似的文件。
- 同一份 PPTX 共用第一页的页面比例。不同尺寸或方向的后续页会按比例居中。
- 默认用 Noto Sans SC 测量和排版，安装包内带 OFL 字体。查看或编辑 PPTX 的电脑也可安装该字体，避免办公软件用替代字体。自定义字体时同时传入 `--font-file` 和 `--font-name`。
- 复杂渐变、叠加素材和形状会近似重建。复杂图像依然可以独立移动和替换，源文件中已经合并的图层和图表数据需要重新绘制或录入。密集小字、数字和跨栏布局需要对照原图校对。

## 本地验证

```bash
python -m unittest discover -s tests -v
```

测试现场生成合成样本，验证中文 OCR、PDF 文字层、独立图片、原生形状、背景和多个输入的导出。使用 [EditableImage2PPTSkill](https://github.com/soulmujoco/EditableImage2PPTSkill) 的 PPTX 生成器。组件及许可证见 [第三方声明](THIRD_PARTY_NOTICES.md)。
