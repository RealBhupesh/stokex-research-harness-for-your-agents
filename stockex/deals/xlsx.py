"""A small, dependency-free .xlsx writer for formula-driven financial models.

It writes Office Open XML SpreadsheetML: shared styles, inline strings,
formulas with cached values (the file opens showing numbers and Excel
recalculates on load), defined names, frozen panes, column widths and tab
colours. It does only what a banker-style model needs.
"""

from datetime import datetime, timezone
import re
import zipfile
from xml.sax.saxutils import escape


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return index


def address(row: int, col: int, *, absolute: bool = False) -> str:
    if absolute:
        return f"${column_letter(col)}${row}"
    return f"{column_letter(col)}{row}"


_CELL = re.compile(r"^([A-Z]+)(\d+)$")


def split_address(ref: str) -> tuple[int, int]:
    match = _CELL.match(ref.replace("$", ""))
    if not match:
        raise ValueError(f"bad cell reference {ref!r}")
    return int(match.group(2)), column_index(match.group(1))


# Number formats. Negative numbers in brackets and zero as a dash, as banks print them.
FORMATS = {
    "general": 0,
    "num": '#,##0.0_);(#,##0.0);"–"_)',
    "num0": '#,##0_);(#,##0);"–"_)',
    "num2": '#,##0.00_);(#,##0.00);"–"_)',
    "pct": '0.0%_);(0.0%);"–"_)',
    "pct2": '0.00%_);(0.00%);"–"_)',
    "mult": '0.0"x"_);(0.0"x");"–"_)',
    "mult2": '0.00"x"_);(0.00"x");"–"_)',
    "price": '"₹"#,##0.00_);("₹"#,##0.00);"–"_)',
    "int": '0',
    "text": "@",
}
FONTS = {
    "normal": '<font><sz val="10"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>',
    "input": '<font><sz val="10"/><color rgb="FF0000FF"/><name val="Calibri"/><family val="2"/></font>',
    "link": '<font><sz val="10"/><color rgb="FF008000"/><name val="Calibri"/><family val="2"/></font>',
    "bold": '<font><b/><sz val="10"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>',
    "header": '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>',
    "title": '<font><b/><sz val="16"/><color rgb="FF1F3864"/><name val="Calibri"/><family val="2"/></font>',
    "subtitle": '<font><i/><sz val="10"/><color rgb="FF595959"/><name val="Calibri"/><family val="2"/></font>',
    "note": '<font><i/><sz val="9"/><color rgb="FF7F7F7F"/><name val="Calibri"/><family val="2"/></font>',
    "section": '<font><b/><sz val="11"/><color rgb="FF1F3864"/><name val="Calibri"/><family val="2"/></font>',
    "bad": '<font><b/><sz val="10"/><color rgb="FFC00000"/><name val="Calibri"/><family val="2"/></font>',
    "good": '<font><b/><sz val="10"/><color rgb="FF00703C"/><name val="Calibri"/><family val="2"/></font>',
}
FILLS = {
    "none": '<fill><patternFill patternType="none"/></fill>',
    "gray125": '<fill><patternFill patternType="gray125"/></fill>',
    "input": '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>',
    "header": '<fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/><bgColor indexed="64"/></patternFill></fill>',
    "band": '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>',
    "key": '<fill><patternFill patternType="solid"><fgColor rgb="FFE2EFDA"/><bgColor indexed="64"/></patternFill></fill>',
}
BORDERS = {
    "none": "<border><left/><right/><top/><bottom/><diagonal/></border>",
    "top": '<border><left/><right/><top style="thin"><color rgb="FF000000"/></top><bottom/><diagonal/></border>',
    "bottom": '<border><left/><right/><top/><bottom style="thin"><color rgb="FF000000"/></bottom><diagonal/></border>',
    "total": '<border><left/><right/><top style="thin"><color rgb="FF000000"/></top>'
             '<bottom style="double"><color rgb="FF000000"/></bottom><diagonal/></border>',
}


class Styles:
    """Registry of cell formats keyed by (font, fill, format, border, horizontal alignment, indent)."""

    def __init__(self):
        self.fonts, self.fills, self.borders = list(FONTS), list(FILLS), list(BORDERS)
        self.custom_formats = {}
        self.xfs = [("normal", "none", "general", "none", None, 0)]
        self._index = {self.xfs[0]: 0}

    def get(self, font="normal", fill="none", fmt="general", border="none", align=None, indent=0) -> int:
        key = (font, fill, fmt, border, align, indent)
        if key not in self._index:
            if fmt not in FORMATS:
                raise ValueError(f"unknown number format {fmt!r}")
            if not isinstance(FORMATS[fmt], int) and fmt not in self.custom_formats:
                self.custom_formats[fmt] = 164 + len(self.custom_formats)
            self._index[key] = len(self.xfs)
            self.xfs.append(key)
        return self._index[key]

    def _format_id(self, fmt: str) -> int:
        return FORMATS[fmt] if isinstance(FORMATS[fmt], int) else self.custom_formats[fmt]

    def xml(self) -> str:
        formats = "".join(f'<numFmt numFmtId="{i}" formatCode="{escape(FORMATS[f], {chr(34): "&quot;"})}"/>'
                          for f, i in self.custom_formats.items())
        xfs = []
        for font, fill, fmt, border, align, indent in self.xfs:
            attrs = (f'numFmtId="{self._format_id(fmt)}" fontId="{self.fonts.index(font)}" '
                     f'fillId="{self.fills.index(fill)}" borderId="{self.borders.index(border)}" xfId="0"'
                     ' applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"')
            if align or indent:
                alignment = f'<alignment{f" horizontal={chr(34)}{align}{chr(34)}" if align else ""}' \
                            f'{f" indent={chr(34)}{indent}{chr(34)}" if indent else ""}/>'
                xfs.append(f'<xf {attrs} applyAlignment="1">{alignment}</xf>')
            else:
                xfs.append(f"<xf {attrs}/>")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<numFmts count="{len(self.custom_formats)}">{formats}</numFmts>'
            f'<fonts count="{len(self.fonts)}">{"".join(FONTS[f] for f in self.fonts)}</fonts>'
            f'<fills count="{len(self.fills)}">{"".join(FILLS[f] for f in self.fills)}</fills>'
            f'<borders count="{len(self.borders)}">{"".join(BORDERS[b] for b in self.borders)}</borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        )


class Cell:
    __slots__ = ("value", "formula", "style")

    def __init__(self, value=None, formula=None, style=0):
        self.value, self.formula, self.style = value, formula, style


class Worksheet:
    def __init__(self, name: str, tab_color: str | None = None):
        if len(name) > 31 or any(ch in name for ch in "[]:*?/\\'"):
            raise ValueError(f"invalid sheet name {name!r}")
        self.name, self.tab_color = name, tab_color
        self.cells: dict[tuple[int, int], Cell] = {}
        self.widths: dict[int, float] = {}
        self.freeze: tuple[int, int] | None = None   # (rows above, columns left)
        self.merges: list[str] = []

    def set(self, row: int, col: int, value=None, *, formula: str | None = None, style: int = 0) -> str:
        if formula is not None and formula.startswith("="):
            formula = formula[1:]
        self.cells[(row, col)] = Cell(value, formula, style)
        return address(row, col)

    def _cell_xml(self, row: int, col: int, cell: Cell) -> str:
        ref = address(row, col)
        style = f' s="{cell.style}"' if cell.style else ""
        value = cell.value
        if cell.formula is not None:
            formula = f"<f>{escape(cell.formula)}</f>"
            if value is None:
                return f'<c r="{ref}"{style}>{formula}</c>'
            if isinstance(value, bool):
                return f'<c r="{ref}"{style} t="b">{formula}<v>{int(value)}</v></c>'
            if isinstance(value, str):
                return f'<c r="{ref}"{style} t="str">{formula}<v>{escape(value)}</v></c>'
            return f'<c r="{ref}"{style}>{formula}<v>{_number(value)}</v></c>'
        if value is None:
            return f'<c r="{ref}"{style}/>'
        if isinstance(value, bool):
            return f'<c r="{ref}"{style} t="b"><v>{int(value)}</v></c>'
        if isinstance(value, str):
            return f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
        return f'<c r="{ref}"{style}><v>{_number(value)}</v></c>'

    def xml(self, selected: bool) -> str:
        rows: dict[int, list] = {}
        for (row, col), cell in sorted(self.cells.items()):
            rows.setdefault(row, []).append(self._cell_xml(row, col, cell))
        sheet_data = "".join(f'<row r="{r}">{"".join(cells)}</row>' for r, cells in sorted(rows.items()))
        pr = f'<sheetPr><tabColor rgb="FF{self.tab_color}"/></sheetPr>' if self.tab_color else ""
        if self.freeze:
            top, left = self.freeze
            corner = address(top + 1, left + 1)
            split = (f' xSplit="{left}"' if left else "") + (f' ySplit="{top}"' if top else "")
            pane_name = "bottomRight" if top and left else ("bottomLeft" if top else "topRight")
            pane = (f'<pane{split} topLeftCell="{corner}" activePane="{pane_name}" state="frozen"/>'
                    f'<selection pane="{pane_name}" activeCell="{corner}" sqref="{corner}"/>')
        else:
            pane = ""
        view = (f'<sheetViews><sheetView showGridLines="0" {"tabSelected=" + chr(34) + "1" + chr(34) + " " if selected else ""}'
                f'zoomScale="90" workbookViewId="0">{pane}</sheetView></sheetViews>')
        cols = ""
        if self.widths:
            cols = "<cols>" + "".join(f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>'
                                      for c, w in sorted(self.widths.items())) + "</cols>"
        dimension = "A1"
        if self.cells:
            max_row = max(r for r, _ in self.cells)
            max_col = max(c for _, c in self.cells)
            dimension = f"A1:{address(max_row, max_col)}"
        merges = ""
        if self.merges:
            merges = f'<mergeCells count="{len(self.merges)}">' + "".join(
                f'<mergeCell ref="{m}"/>' for m in self.merges) + "</mergeCells>"
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'{pr}<dimension ref="{dimension}"/>{view}<sheetFormatPr defaultRowHeight="13.8"/>{cols}'
                f"<sheetData>{sheet_data}</sheetData>{merges}"
                '<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
                '<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
                "</worksheet>")


def _number(value) -> str:
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("cannot write a non-finite number to a workbook")
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text


class Workbook:
    def __init__(self, *, title: str = "", author: str = "STOCKEX"):
        self.sheets: list[Worksheet] = []
        self.styles = Styles()
        self.names: dict[str, str] = {}     # defined name -> "Sheet!$A$1"
        self.title, self.author = title, author

    def add_sheet(self, name: str, tab_color: str | None = None) -> Worksheet:
        if any(s.name == name for s in self.sheets):
            raise ValueError(f"duplicate sheet {name!r}")
        sheet = Worksheet(name, tab_color)
        self.sheets.append(sheet)
        return sheet

    def sheet(self, name: str) -> Worksheet:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        raise KeyError(name)

    def define(self, name: str, sheet: str, row: int, col: int) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) or _CELL.match(name.upper()):
            raise ValueError(f"invalid defined name {name!r}")
        self.names[name] = f"{sheet}!{address(row, col, absolute=True)}"
        return name

    def save(self, path) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sheets_xml = "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, s in enumerate(self.sheets, 1))
        names_xml = ""
        if self.names:
            names_xml = "<definedNames>" + "".join(
                f'<definedName name="{n}">{escape(ref)}</definedName>' for n, ref in sorted(self.names.items())
            ) + "</definedNames>"
        workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<bookViews><workbookView activeTab="0"/></bookViews>'
                    f"<sheets>{sheets_xml}</sheets>{names_xml}"
                    '<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
        n = len(self.sheets)
        rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                       f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
        rels += (f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                 'relationships/styles" Target="styles.xml"/>')
        content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
                         'officedocument.spreadsheetml.sheet.main+xml"/>'
                         + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                                   'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                                   for i in range(1, n + 1))
                         + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-'
                         'officedocument.spreadsheetml.styles+xml"/>'
                         '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-'
                         'package.core-properties+xml"/>'
                         '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-'
                         'officedocument.extended-properties+xml"/></Types>')
        root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/officeDocument" Target="xl/workbook.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/'
                     'metadata/core-properties" Target="docProps/core.xml"/>'
                     '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/extended-properties" Target="docProps/app.xml"/></Relationships>')
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f"<dc:title>{escape(self.title)}</dc:title><dc:creator>{escape(self.author)}</dc:creator>"
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>')
        app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
               "<Application>STOCKEX</Application></Properties>")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("docProps/core.xml", core)
            archive.writestr("docProps/app.xml", app)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels",
                             '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                             f"{rels}</Relationships>")
            archive.writestr("xl/styles.xml", self.styles.xml())
            for i, sheet in enumerate(self.sheets, 1):
                archive.writestr(f"xl/worksheets/sheet{i}.xml", sheet.xml(selected=i == 1))
