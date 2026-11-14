import re
from base64 import b64decode
from binascii import Error as Base64Error
from collections import Counter
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import pdfplumber
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError
from markdown_it import MarkdownIt
from pdfminer.pdfexceptions import PDFException
from pdfminer.psparser import PSEOF
from PIL import Image, UnidentifiedImageError

from models.rag import Block, InvalidDocument


POINT_ID_PATTERN = r"(?<![\w.-])[A-Z]{1,10}-\d+(?:\.\d+)*-\d{2,6}(?![\w-]|\.\d)"
POINT_ID = re.compile(POINT_ID_PATTERN, re.IGNORECASE | re.ASCII)
FOOTER_ERROR = re.compile(r"^Ошибка! Используйте вкладку.*", re.IGNORECASE)
INLINE_IMAGE_DATA = re.compile(r"data:image/[^\s;,()]+;base64,[A-Za-z0-9+/=]+")
MAX_PAGES = 300
MAX_BLOCKS = 15000
MAX_BLOCK_CHARS = 2400
MAX_IMAGES_BYTES = 90 * 1024 * 1024


def identifiers(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group().upper() for match in POINT_ID.finditer(text)))


def leading_identifier(text: str) -> tuple[str, ...]:
    match = POINT_ID.match(text.lstrip())
    return (match.group().upper(),) if match else ()


def row_identifiers(cells: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(cell.upper() for cell in cells if POINT_ID.fullmatch(cell)))


def extract_blocks(data: bytes, format: str) -> list[Block]:
    try:
        blocks = {"pdf": extract_pdf, "docx": extract_docx, "md": extract_markdown}[format](data)
    except (BadZipFile, PDFException, PSEOF, XMLSyntaxError, UnicodeError, KeyError) as error:
        raise InvalidDocument("invalid_file") from error
    if not blocks:
        raise InvalidDocument("empty_document")
    if len(blocks) > MAX_BLOCKS or sum(len(block.image or b"") for block in blocks) > MAX_IMAGES_BYTES:
        raise InvalidDocument("document_too_large")
    return blocks


def text_blocks(text: str, **location) -> list[Block]:
    location["identifiers"] = leading_identifier(text) or location.get("identifiers", ())
    return [
        Block("text", part, **location)
        for index in range(0, len(text), MAX_BLOCK_CHARS)
        if (part := text[index:index + MAX_BLOCK_CHARS].strip())
    ]


def clean_cell(value: str | None) -> str:
    return " ".join((value or "").split())


def table_blocks(rows, table_id: str, **location) -> list[Block]:
    if not rows:
        return []
    columns = tuple(clean_cell(value) for value in rows[0])
    return [
        Block(
            "table_row",
            " | ".join(cells),
            cells=cells,
            columns=columns,
            table_id=table_id,
            identifiers=row_identifiers(cells),
            **location,
        )
        for row in rows[1:] or rows
        if any(cells := tuple(clean_cell(value) for value in row))
    ]


def image_png(blob: bytes) -> bytes:
    with Image.open(BytesIO(blob)) as image:
        image.thumbnail((2200, 2200))
        buffer = BytesIO()
        image.convert("RGB").save(buffer, "PNG")
        return buffer.getvalue()


def extract_docx(data: bytes) -> list[Block]:
    with ZipFile(BytesIO(data)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 120 * 1024 * 1024:
            raise InvalidDocument("document_too_large")
    document = Document(BytesIO(data))
    blocks: list[Block] = []
    headings: list[tuple[int, str]] = []
    for index, item in enumerate(document.iter_inner_content()):
        section = tuple(title for _, title in headings)
        if isinstance(item, Table):
            blocks.extend(table_blocks(
                [[cell.text for cell in row.cells] for row in item.rows],
                f"docx:{index}", section=section,
            ))
        elif isinstance(item, Paragraph):
            heading = re.fullmatch(r"Heading (\d+)", item.style.name if item.style else "")
            if heading and item.text.strip():
                level = int(heading[1])
                headings = [(depth, title) for depth, title in headings if depth < level]
                headings.append((level, item.text.strip()))
                section = tuple(title for _, title in headings)
                blocks.append(Block(
                    "heading", item.text.strip(), section=section,
                    identifiers=leading_identifier(item.text),
                ))
            else:
                inherited = next((codes for title in reversed(section) if (codes := leading_identifier(title))), ())
                blocks.extend(text_blocks(item.text, section=section, identifiers=inherited))
        for element in item._element.xpath(".//a:blip"):
            relationship = element.get(qn("r:embed"))
            if relationship:
                try:
                    image = image_png(document.part.related_parts[relationship].blob)
                except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as error:
                    raise InvalidDocument("unsupported_image") from error
                blocks.append(Block("visual", section=section, image=image))
    return blocks


def extract_markdown(data: bytes) -> list[Block]:
    source = data.decode("utf-8-sig")
    lines = source.splitlines()
    tokens = MarkdownIt("commonmark").enable("table").parse(source)
    blocks: list[Block] = []
    headings: list[tuple[int, str]] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        section = tuple(title for _, title in headings)
        if token.type == "heading_open":
            title = tokens[position + 1].content
            level = int(token.tag[1:])
            headings = [(depth, name) for depth, name in headings if depth < level]
            headings.append((level, title))
            blocks.append(Block(
                "heading", title, section=tuple(name for _, name in headings),
                identifiers=leading_identifier(title),
            ))
            position += 2
        elif token.type == "table_open":
            rows = []
            start = position
            while tokens[position].type != "table_close":
                if tokens[position].type == "tr_open":
                    rows.append([])
                elif tokens[position].type == "inline":
                    rows[-1].append(tokens[position].content)
                position += 1
            blocks.extend(table_blocks(rows, f"md:{start}", section=section))
        elif token.type in ("paragraph_open", "fence", "code_block", "html_block") and token.map:
            first, end = token.map
            inherited = next((codes for title in reversed(section) if (codes := leading_identifier(title))), ())
            text = "\n".join(lines[first:end])
            if token.type == "paragraph_open":
                text = INLINE_IMAGE_DATA.sub("", text)
            blocks.extend(text_blocks(text, section=section, identifiers=inherited))
        elif token.type == "inline":
            for child in token.children or ():
                src = child.attrGet("src")
                if child.type != "image" or not src or not src.startswith("data:image/"):
                    continue
                try:
                    header, encoded = src.split(",", 1)
                    if not header.endswith(";base64"):
                        raise ValueError("unsupported image encoding")
                    image = image_png(b64decode(encoded, validate=True))
                except (Base64Error, ValueError, Image.DecompressionBombError, OSError) as error:
                    raise InvalidDocument("unsupported_image") from error
                blocks.append(Block("visual", section=section, image=image, label=child.content))
        position += 1
    return blocks


def pdf_png(page, box) -> bytes:
    target = page.crop(box) if box != page.bbox else page
    image = target.to_image(resolution=min(330, 2200 * 72 / max(target.width, target.height)))
    buffer = BytesIO()
    image.original.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def pdf_table_context(lines, box) -> str:
    preceding = [
        line["text"] for line in lines
        if 0 <= box[1] - line["bottom"] <= 62 and not FOOTER_ERROR.match(line["text"])
        and re.search(r"[^\W\d_]", line["text"])
    ]
    return " ".join(preceding)[-420:]


def pdf_tables(page, lines):
    tables = page.find_tables({
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "intersection_tolerance": 3,
    })
    for index, table in enumerate(sorted(tables, key=lambda item: item.bbox[1])):
        box = table.bbox
        rows = table.extract(x_tolerance=1, y_tolerance=2)
        if len(rows) < 2 or len(rows[0]) < 2:
            continue
        table_id = f"pdf:{page.page_number}:{index}"
        matching = [
            (index, row, values)
            for index, (row, values) in enumerate(zip(table.rows, rows, strict=True))
            if any(POINT_ID.fullmatch(clean_cell(value)) for value in values)
        ]
        if matching:
            first_index, first_row, _ = matching[0]
            header = next(
                (row for row in reversed(rows[:first_index])
                 if sum(bool(clean_cell(cell)) for cell in row) >= 2),
                [],
            )
            columns = [
                index for index in range(len(rows[0]))
                if (header and clean_cell(header[index]))
                or any(clean_cell(values[index]) for _, _, values in matching)
            ]
            label = " ".join(
                line["text"] for line in lines if box[1] <= line["top"] < first_row.bbox[1]
            )[-420:]
            for _, row, values in matching:
                cells = tuple(clean_cell(values[index]) for index in columns)
                row_ids = tuple(
                    clean_cell(cell).upper() for cell in values if POINT_ID.fullmatch(clean_cell(cell))
                )
                yield row.bbox, [Block(
                    "table_row", " | ".join(cells), page=page.page_number, box=row.bbox,
                    table_id=table_id, label=label, cells=cells, identifiers=row_ids,
                    columns=tuple(clean_cell(header[index]) for index in columns) if header else (),
                )]
            continue
        widths = [sum(bool(clean_cell(value)) for value in row) for row in rows]
        if min(widths) >= 2 and all(all(cell is not None for cell in row) for row in rows):
            yield box, table_blocks(
                rows, table_id, page=page.page_number, box=box,
                label=pdf_table_context(lines, box),
            )
            continue
        intervals = []
        start = None
        table_rows = 0
        for row, width in zip(table.rows, widths, strict=True):
            full_width = [
                cell for cell in row.cells
                if cell and cell[2] - cell[0] > (box[2] - box[0]) * 0.9
            ]
            if full_width and width == 1:
                if start is not None and table_rows >= 2:
                    intervals.append((start, min(cell[1] for cell in full_width)))
                start, table_rows = None, 0
            elif width >= 2:
                if start is None:
                    start = row.bbox[1]
                table_rows += 1
        if start is not None and table_rows >= 2:
            intervals.append((start, box[3]))
        for part, (top, bottom) in enumerate(intervals):
            crop = (box[0], top, box[2], bottom)
            if bottom - top < 14:
                continue
            yield crop, [Block(
                "visual", page=page.page_number, box=crop, table_id=f"{table_id}:{part}",
                image=pdf_png(page, crop), label=pdf_table_context(lines, crop),
            )]


def within(line, box) -> bool:
    return (
        box[0] - 2 <= (line["x0"] + line["x1"]) / 2 <= box[2] + 2
        and box[1] - 2 <= (line["top"] + line["bottom"]) / 2 <= box[3] + 2
    )


def pdf_text_blocks(lines, page_number: int):
    current = []
    current_id = ()

    def flush():
        if not current:
            return None
        box = (
            min(line["x0"] for line in current), current[0]["top"],
            max(line["x1"] for line in current), current[-1]["bottom"],
        )
        text = "\n".join(line["text"] for line in current)
        parts = text_blocks(text, page=page_number, box=box, identifiers=current_id)
        return box[1], parts

    for line in lines:
        text = line["text"].strip()
        if not text or FOOTER_ERROR.match(text) or re.fullmatch(r"\d{1,3}", text):
            continue
        match = POINT_ID.match(text)
        if current and (
            match or not current_id and line["top"] - current[-1]["bottom"] > 7
        ):
            yield flush()
            current.clear()
            current_id = ()
        if match:
            current_id = (match.group().upper(),)
        current.append(line)
    if current:
        yield flush()


def extract_pdf(data: bytes) -> list[Block]:
    result: list[Block] = []
    total_images = 0
    with pdfplumber.open(BytesIO(data)) as document:
        if len(document.pages) > MAX_PAGES:
            raise InvalidDocument("document_too_large")
        page_lines = [
            page.dedupe_chars(tolerance=0.8).extract_text_lines(layout=False)
            for page in document.pages
        ]
        repeated = Counter(
            margin_text(line["text"])
            for page, lines in zip(document.pages, page_lines, strict=True)
            for line in lines if in_margin(line, page)
        )
        for page, raw_lines in zip(document.pages, page_lines, strict=True):
            lines = [
                line for line in raw_lines if not (
                    in_margin(line, page) and repeated[margin_text(line["text"])] >= 3
                )
            ]
            page_items: list[tuple[float, list[Block]]] = []
            if not any(re.search(r"[^\W\d_]", line["text"]) for line in lines):
                if page.images or page.curves or page.lines or page.rects:
                    page_items.append((0, [Block(
                        "scan", page=page.page_number, box=page.bbox, image=pdf_png(page, page.bbox)
                    )]))
            else:
                tables = list(pdf_tables(page, lines))
                page_items.extend((box[1], blocks) for box, blocks in tables)
                page_items.extend(pdf_text_blocks(
                    [line for line in lines if not any(within(line, box) for box, _ in tables)],
                    page.page_number,
                ))
                for image in page.images:
                    box = (
                        max(page.bbox[0], image["x0"]), max(page.bbox[1], image["top"]),
                        min(page.bbox[2], image["x1"]), min(page.bbox[3], image["bottom"]),
                    )
                    if box[2] - box[0] >= 80 and box[3] - box[1] >= 35:
                        page_items.append((box[1], [Block(
                            "visual", page=page.page_number, box=box, image=pdf_png(page, box),
                            label=pdf_table_context(lines, box),
                        )]))
            for _, blocks in sorted(page_items, key=lambda item: item[0]):
                total_images += sum(len(block.image or b"") for block in blocks)
                if total_images > MAX_IMAGES_BYTES or len(result) + len(blocks) > MAX_BLOCKS:
                    raise InvalidDocument("document_too_large")
                result.extend(blocks)
            page.close()
    return result


def in_margin(line, page) -> bool:
    return line["top"] - page.bbox[1] < 48 or page.bbox[3] - line["bottom"] < 58


def margin_text(text: str) -> str:
    return re.sub(r"\s*(?:[–-]\s*)?\d+\s*$", "", text).strip()
