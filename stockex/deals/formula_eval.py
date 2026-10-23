"""An independent evaluator for the Excel formula subset the deal workbook uses.

It does two jobs:
- It fills the cached values written into the workbook, so the file opens showing numbers.
- It is the integrity proof. Tests reload the saved .xlsx, recompute every
  formula from the inputs alone, and compare the results with the Python
  engine, which is a separate implementation of the same model.

Supported:
- arithmetic + - * / ^, comparisons and &;
- cell references, ranges, cross-sheet references and defined names;
- SUM, MIN, MAX, AVERAGE, MEDIAN, QUARTILE, ABS, IF, AND, OR, NOT, IRR, INDEX,
  CHOOSE, ROUND, IFERROR, SUMPRODUCT and COUNT.
"""

import math
import re
import xml.etree.ElementTree as ET
import zipfile

from .xlsx import column_index, column_letter, split_address


class FormulaError(Exception):
    pass


_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"]|"")*")
  | (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<sheetref>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
  | (?P<func>[A-Za-z_][A-Za-z0-9_.]*(?=\())
  | (?P<ref>\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![A-Za-z0-9_]))
  | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
  | (?P<op><>|<=|>=|[-+*/^&=<>(),])
""", re.VERBOSE)


def tokenize(formula: str) -> list[tuple[str, str]]:
    tokens, position = [], 0
    while position < len(formula):
        match = _TOKEN.match(formula, position)
        if not match:
            raise FormulaError(f"cannot parse {formula[position:]!r} in {formula!r}")
        kind = match.lastgroup
        if kind != "ws":
            tokens.append((kind, match.group()))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.i = tokens, 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        token = self.peek()
        if value is not None and token[1] != value:
            raise FormulaError(f"expected {value!r}, found {token[1]!r}")
        self.i += 1
        return token

    def parse(self):
        node = self.comparison()
        if self.i != len(self.tokens):
            raise FormulaError(f"unexpected {self.peek()[1]!r}")
        return node

    def comparison(self):
        node = self.concat()
        while self.peek()[1] in {"=", "<>", "<", ">", "<=", ">="}:
            op = self.take()[1]
            node = ("bin", op, node, self.concat())
        return node

    def concat(self):
        node = self.additive()
        while self.peek()[1] == "&":
            self.take()
            node = ("bin", "&", node, self.additive())
        return node

    def additive(self):
        node = self.term()
        while self.peek()[1] in {"+", "-"}:
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.power()
        while self.peek()[1] in {"*", "/"}:
            op = self.take()[1]
            node = ("bin", op, node, self.power())
        return node

    def power(self):
        node = self.unary()
        while self.peek()[1] == "^":
            self.take()
            node = ("bin", "^", node, self.unary())
        return node

    def unary(self):
        if self.peek()[1] in {"-", "+"}:
            op = self.take()[1]
            operand = self.unary()
            return ("neg", operand) if op == "-" else operand
        return self.primary()

    def primary(self):
        kind, text = self.take()
        if kind == "number":
            return ("num", float(text))
        if kind == "string":
            return ("str", text[1:-1].replace('""', '"'))
        if kind in {"ref", "sheetref"}:
            sheet = None
            if kind == "sheetref":
                sheet, text = text.rsplit("!", 1)
                if sheet.startswith("'"):
                    sheet = sheet[1:-1].replace("''", "'")
            if ":" in text:
                first, last = text.split(":")
                (r1, c1), (r2, c2) = split_address(first), split_address(last)
                return ("range", sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
            row, col = split_address(text)
            return ("ref", sheet, row, col)
        if kind == "func":
            name = text.upper().removeprefix("_XLFN.")
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.comparison())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.comparison())
            self.take(")")
            return ("call", name, args)
        if kind == "name":
            upper = text.upper()
            if upper in {"TRUE", "FALSE"}:
                return ("bool", upper == "TRUE")
            return ("name", text)
        if text == "(":
            node = self.comparison()
            self.take(")")
            return node
        raise FormulaError(f"unexpected token {text!r}")


def parse(formula: str):
    return _Parser(tokenize(formula)).parse()


class Book:
    """Cells per sheet: {(row, col): (value, formula)} plus defined names."""

    def __init__(self, sheets: dict, names: dict):
        self.sheets, self.names = sheets, names

    @classmethod
    def from_workbook(cls, workbook) -> "Book":
        sheets = {s.name: {k: (c.value, c.formula) for k, c in s.cells.items()} for s in workbook.sheets}
        return cls(sheets, dict(workbook.names))

    @classmethod
    def from_xlsx(cls, path) -> "Book":
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
              "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{rel_ns}Relationship")}
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", ns):
                    shared.append("".join(t.text or "" for t in item.iter(f"{{{ns['m']}}}t")))
            names = {}
            for defined in workbook.iter(f"{{{ns['m']}}}definedName"):
                if defined.get("localSheetId") is None and not defined.get("name", "").startswith("_xlnm"):
                    names[defined.get("name")] = defined.text
            sheets = {}
            for sheet in workbook.find("m:sheets", ns):
                target = targets[sheet.get(f"{{{ns['r']}}}id")].lstrip("/")
                target = target if target.startswith("xl/") else "xl/" + target
                cells = {}
                root = ET.fromstring(archive.read(target))
                for c in root.iter(f"{{{ns['m']}}}c"):
                    row, col = split_address(c.get("r"))
                    kind = c.get("t")
                    f = c.find("m:f", ns)
                    v = c.find("m:v", ns)
                    if kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                    elif v is None:
                        value = None
                    elif kind == "s":
                        value = shared[int(v.text)]
                    elif kind in {"str", "e"}:
                        value = v.text or ""
                    elif kind == "b":
                        value = v.text == "1"
                    else:
                        value = float(v.text)
                    formula = f.text if f is not None and f.text else None
                    cells[(row, col)] = (value, formula)
                sheets[sheet.get("name")] = cells
        return cls(sheets, names)


class Evaluator:
    def __init__(self, book: Book):
        self.book = book
        self.cache: dict = {}
        self.parsed: dict = {}
        self.stack: set = set()

    def value(self, sheet: str, row: int, col: int):
        key = (sheet, row, col)
        if key in self.cache:
            return self.cache[key]
        cell = self.book.sheets.get(sheet, {}).get((row, col))
        if cell is None:
            return None
        value, formula = cell
        if formula is None:
            return value
        if key in self.stack:
            raise FormulaError(f"circular reference at {sheet}!{row},{col}")
        self.stack.add(key)
        try:
            if key not in self.parsed:
                self.parsed[key] = parse(formula)
            try:
                result = self.eval(self.parsed[key], sheet)
            except FormulaError as error:
                if not str(error).startswith("at "):
                    raise FormulaError(f"at {sheet}!{column_letter(col)}{row} ({formula}): {error}") from error
                raise
            if isinstance(result, list):
                raise FormulaError(f"range used as a value in {sheet}!{row},{col}: {formula}")
        finally:
            self.stack.discard(key)
        self.cache[key] = result
        return result

    def evaluate_all(self) -> dict:
        return {(sheet, row, col): self.value(sheet, row, col)
                for sheet, cells in self.book.sheets.items() for (row, col), (_, f) in cells.items() if f}

    def _name(self, name: str, sheet: str):
        target = self.book.names.get(name)
        if target is None:
            raise FormulaError(f"unknown name {name!r}")
        return self.eval(parse(target), sheet)

    def eval(self, node, sheet):
        kind = node[0]
        if kind in {"num", "str", "bool"}:
            return node[1]
        if kind == "ref":
            return self.value(node[1] or sheet, node[2], node[3])
        if kind == "range":
            target = node[1] or sheet
            return [[self.value(target, r, c) for c in range(node[3], node[5] + 1)] for r in range(node[2], node[4] + 1)]
        if kind == "name":
            return self._name(node[1], sheet)
        if kind == "neg":
            return -_num(self.eval(node[1], sheet))
        if kind == "bin":
            return self._binary(node[1], self.eval(node[2], sheet), self.eval(node[3], sheet))
        if kind == "call":
            return self._call(node[1], node[2], sheet)
        raise FormulaError(f"bad node {node!r}")

    @staticmethod
    def _binary(op, left, right):
        if op == "&":
            return _text(left) + _text(right)
        if op in {"=", "<>", "<", ">", "<=", ">="}:
            a, b = (left if left is not None else 0), (right if right is not None else 0)
            if isinstance(a, str) or isinstance(b, str):
                a, b = _text(a).upper(), _text(b).upper()
            return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        a, b = _num(left), _num(right)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise FormulaError("#DIV/0!")
            return a / b
        if op == "^":
            try:
                result = a ** b
            except (OverflowError, ZeroDivisionError) as error:
                raise FormulaError("#NUM!") from error
            if isinstance(result, complex):
                raise FormulaError("#NUM!")
            return result
        raise FormulaError(f"unknown operator {op}")

    def _numbers(self, args, sheet) -> list[float]:
        values = []
        for arg in args:
            result = self.eval(arg, sheet)
            if isinstance(result, list):
                values.extend(v for row in result for v in row if isinstance(v, (int, float)) and not isinstance(v, bool))
            elif result is not None:
                values.append(_num(result))
        return values

    def _call(self, name, args, sheet):
        if name == "IF":
            condition = self.eval(args[0], sheet)
            if _truthy(condition):
                return self.eval(args[1], sheet)
            return self.eval(args[2], sheet) if len(args) > 2 else False
        if name == "IFERROR":
            try:
                return self.eval(args[0], sheet)
            except FormulaError:
                return self.eval(args[1], sheet)
        if name == "CHOOSE":
            index = int(_num(self.eval(args[0], sheet)))
            if not 1 <= index < len(args):
                raise FormulaError("#VALUE!")
            return self.eval(args[index], sheet)
        if name in {"AND", "OR"}:
            flags = []
            for arg in args:
                result = self.eval(arg, sheet)
                flags.extend([_truthy(v) for row in result for v in row] if isinstance(result, list) else [_truthy(result)])
            return all(flags) if name == "AND" else any(flags)
        if name == "NOT":
            return not _truthy(self.eval(args[0], sheet))
        if name == "INDEX":
            block = self.eval(args[0], sheet)
            if not isinstance(block, list):
                raise FormulaError("INDEX needs a range")
            first = int(_num(self.eval(args[1], sheet)))
            if len(args) > 2:
                row, col = first, int(_num(self.eval(args[2], sheet)))
            elif len(block) == 1:
                row, col = 1, first
            else:
                row, col = first, 1
            if not (1 <= row <= len(block) and 1 <= col <= len(block[0])):
                raise FormulaError("#REF!")
            return block[row - 1][col - 1]
        if name == "SUMPRODUCT":
            blocks = [self.eval(arg, sheet) for arg in args]
            flat = [[_num(v) if v is not None else 0.0 for row in b for v in row] for b in blocks]
            if len({len(f) for f in flat}) != 1:
                raise FormulaError("#VALUE!")
            return sum(math.prod(items) for items in zip(*flat))
        if name == "IRR":
            block = self.eval(args[0], sheet)
            flows = [_num(v) for row in block for v in row if v is not None]
            return _irr(flows)
        if name == "QUARTILE":
            values = sorted(self._numbers(args[:1], sheet))
            q = _num(self.eval(args[1], sheet))
            if not values or not 0 <= q <= 4:
                raise FormulaError("#NUM!")
            position = (len(values) - 1) * q / 4
            low = int(position)
            high = min(low + 1, len(values) - 1)
            return values[low] + (values[high] - values[low]) * (position - low)
        if name == "ROUND":
            value, digits = _num(self.eval(args[0], sheet)), int(_num(self.eval(args[1], sheet)))
            scale = 10 ** digits
            return math.floor(abs(value) * scale + 0.5) / scale * (1 if value >= 0 else -1)
        if name == "ABS":
            return abs(_num(self.eval(args[0], sheet)))
        values = self._numbers(args, sheet)
        if name == "SUM":
            return sum(values)
        if name == "COUNT":
            return float(len(values))
        if name == "MIN":
            return min(values) if values else 0.0
        if name == "MAX":
            return max(values) if values else 0.0
        if name == "AVERAGE":
            if not values:
                raise FormulaError("#DIV/0!")
            return sum(values) / len(values)
        if name == "MEDIAN":
            if not values:
                raise FormulaError("#NUM!")
            ordered = sorted(values)
            mid = len(ordered) // 2
            return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        raise FormulaError(f"unsupported function {name}")


def _irr(flows: list[float]) -> float:
    def npv(rate):
        return sum(f / (1 + rate) ** t for t, f in enumerate(flows))
    low, high = -0.9999, 10.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        raise FormulaError("#NUM!")
    for _ in range(300):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-12 or high - low < 1e-12:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def _num(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        raise FormulaError("#VALUE! (range in arithmetic)")
    try:
        return float(value)
    except ValueError as error:
        raise FormulaError(f"#VALUE! ({value!r})") from error


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _truthy(value) -> bool:
    if isinstance(value, str):
        raise FormulaError("#VALUE! (text as condition)")
    return bool(_num(value))


__all__ = ["Book", "Evaluator", "FormulaError", "parse", "tokenize", "column_index"]
