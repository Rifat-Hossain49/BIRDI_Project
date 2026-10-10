"""Typed algorithm IR extraction and deterministic Python compilation.

The IR is intentionally small and text based.  It keeps ordinary control-flow
when the source program needs it, but lifts common reusable algorithmic actions
into stable operators such as FILTER, MEAN, GCD, LCM, SUM, COUNT, and SORT.
That gives the decoder a much easier target than loose graph JSON labels while
still keeping final code generation deterministic.
"""

from __future__ import annotations

import ast
import keyword
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class AlgorithmIR:
    lines: list[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        return "\n".join(line.rstrip() for line in self.lines if line.strip())


def ir_from_code(instruction: Any, input_value: Any, code: Any) -> AlgorithmIR:
    return CodeAlgorithmIRExtractor().extract(instruction, input_value, code)


def compile_ir_to_python(ir_text: str, function_name: str = "solution") -> str:
    """Compile typed IR into Python without calling an LLM."""

    lines = [_clean_line(line) for line in str(ir_text).splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    safe_name = _safe_identifier(function_name, "solution")
    params: list[str] = []

    if lines and lines[0].upper().startswith("FUNC "):
        name, params = _parse_func(lines[0])
        if not safe_name:
            safe_name = _safe_identifier(name, "solution")
        lines = lines[1:]

    body: list[str] = []
    indent = 1
    needs_math = _needs_math(lines)

    if needs_math:
        body.append("    import math")

    for raw_line in lines:
        upper = raw_line.upper()
        if upper == "END":
            indent = max(1, indent - 1)
            continue
        if upper == "ELSE":
            indent = max(1, indent - 1)
            body.append("    " * indent + "else:")
            indent += 1
            continue

        emitted, opens_block = _compile_ir_line(raw_line)
        if emitted:
            for line in emitted:
                body.append("    " * indent + line)
        if opens_block:
            indent += 1

    if not _has_executable_line(body):
        body = ["    return None"]

    header = f"def {safe_name}({', '.join(params)}):"
    return "\n".join([header, *body])


class CodeAlgorithmIRExtractor:
    def extract(self, instruction: Any, input_value: Any, code: Any) -> AlgorithmIR:
        instruction_text = _clean_text(instruction)
        code_text = _clean_code(code)
        if not code_text:
            return _fallback_ir(instruction_text, _clean_text(input_value), "empty_code")

        try:
            tree = ast.parse(code_text)
        except SyntaxError as exc:
            return _fallback_ir(instruction_text, _clean_text(input_value), f"syntax_error:{exc.msg}")

        func = _first_function(tree)
        if func is not None:
            name = _safe_identifier(func.name, "solution")
            params = [_safe_identifier(arg.arg, "arg") for arg in func.args.args]
            statements = list(func.body)
        else:
            name = "solution"
            params = _infer_params_from_input(input_value)
            statements = list(tree.body)

        lines = [f"FUNC {name}({', '.join(params)})"]
        self._emit_statements(statements, lines)
        if not any(line.startswith("RETURN ") for line in lines):
            lines.append("RETURN None")

        confidence = 0.94 if func is not None else 0.82
        return AlgorithmIR(
            lines=lines,
            confidence=confidence,
            metadata={"source": "python_ast_typed_algorithm_ir", "parse_ok": True},
        )

    def _emit_statements(self, statements: Iterable[ast.stmt], lines: list[str]) -> None:
        for stmt in statements:
            self._emit_statement(stmt, lines)

    def _emit_statement(self, stmt: ast.stmt, lines: list[str]) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._emit_statements(stmt.body, lines)
            return

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            lines.append(f"FOR {_unparse(stmt.target)} IN {_unparse(stmt.iter)}")
            self._emit_statements(stmt.body, lines)
            if stmt.orelse:
                lines.append("ELSE")
                self._emit_statements(stmt.orelse, lines)
            lines.append("END")
            return

        if isinstance(stmt, ast.While):
            lines.append(f"WHILE {_unparse(stmt.test)}")
            self._emit_statements(stmt.body, lines)
            if stmt.orelse:
                lines.append("ELSE")
                self._emit_statements(stmt.orelse, lines)
            lines.append("END")
            return

        if isinstance(stmt, ast.If):
            lines.append(f"IF {_unparse(stmt.test)}")
            self._emit_statements(stmt.body, lines)
            if stmt.orelse:
                lines.append("ELSE")
                self._emit_statements(stmt.orelse, lines)
            lines.append("END")
            return

        if isinstance(stmt, ast.Return):
            lines.append(_return_ir(stmt.value))
            return

        if isinstance(stmt, ast.Assign):
            target = _targets_text(stmt.targets)
            lines.append(_assign_ir(target, stmt.value, is_initial=True))
            return

        if isinstance(stmt, ast.AnnAssign):
            target = _unparse(stmt.target)
            lines.append(_assign_ir(target, stmt.value, is_initial=True))
            return

        if isinstance(stmt, ast.AugAssign):
            lines.append(f"AUG {_unparse(stmt.target)} {_op_symbol(stmt.op)}= {_unparse(stmt.value)}")
            return

        if isinstance(stmt, ast.Expr):
            expr = _unparse(stmt.value)
            if expr:
                lines.append(f"EXPR {expr}")
            return

        if isinstance(stmt, (ast.Break, ast.Continue)):
            lines.append(stmt.__class__.__name__.upper())
            return

        text = _unparse(stmt)
        if text:
            lines.append(f"STMT {text}")


def _assign_ir(target: str, value: ast.AST | None, is_initial: bool) -> str:
    if value is None:
        return f"INIT {target} = None"

    filter_parts = _listcomp_filter_parts(value)
    if filter_parts is not None:
        element, source, condition = filter_parts
        return f"FILTER {target} = {source} AS {element} WHERE {condition}"

    mean_source = _mean_source(value)
    if mean_source:
        return f"MEAN {target} = {mean_source}"

    call = _call_info(value)
    if call and call[0] in {"gcd", "lcm"}:
        return f"{call[0].upper()} {target} = {', '.join(call[1])}"
    if call and call[0] in {"sum", "len", "count", "sorted", "min", "max"}:
        op = {"len": "COUNT", "sorted": "SORT"}.get(call[0], call[0].upper())
        return f"{op} {target} = {', '.join(call[1])}"

    prefix = "INIT" if is_initial else "ASSIGN"
    return f"{prefix} {target} = {_unparse(value)}"


def _return_ir(value: ast.AST | None) -> str:
    if value is None:
        return "RETURN None"
    mean_source = _mean_source(value)
    if mean_source:
        return f"RETURN MEAN({mean_source})"
    call = _call_info(value)
    if call and call[0] in {"gcd", "lcm", "sum", "len", "count", "sorted", "min", "max"}:
        op = {"len": "COUNT", "sorted": "SORT"}.get(call[0], call[0].upper())
        return f"RETURN {op}({', '.join(call[1])})"
    return f"RETURN {_unparse(value)}"


def _compile_ir_line(line: str) -> tuple[list[str], bool]:
    if line.startswith("FOR "):
        match = re.match(r"FOR\s+(.+?)\s+IN\s+(.+)$", line, flags=re.IGNORECASE)
        if match:
            return [f"for {match.group(1)} in {match.group(2)}:"], True
    if line.startswith("WHILE "):
        return [f"while {line[6:].strip()}:"], True
    if line.startswith("IF "):
        return [f"if {line[3:].strip()}:"], True
    if line in {"BREAK", "CONTINUE"}:
        return [line.lower()], False
    if line.startswith("FILTER "):
        return [_compile_filter(line)], False
    if line.startswith("MEAN "):
        target, source = _parse_op_assignment(line, "MEAN")
        return [f"{target} = (sum({source}) / len({source})) if {source} else 0"], False
    if line.startswith("SUM "):
        target, source = _parse_op_assignment(line, "SUM")
        return [f"{target} = sum({source})"], False
    if line.startswith("COUNT "):
        target, source = _parse_op_assignment(line, "COUNT")
        return [f"{target} = len({source})"], False
    if line.startswith("SORT "):
        target, source = _parse_op_assignment(line, "SORT")
        return [f"{target} = sorted({source})"], False
    if line.startswith("MIN "):
        target, source = _parse_op_assignment(line, "MIN")
        return [f"{target} = min({source})"], False
    if line.startswith("MAX "):
        target, source = _parse_op_assignment(line, "MAX")
        return [f"{target} = max({source})"], False
    if line.startswith("GCD "):
        target, args = _parse_op_args_assignment(line, "GCD")
        return [f"{target} = math.gcd({args})"], False
    if line.startswith("LCM "):
        target, args = _parse_op_args_assignment(line, "LCM")
        return [f"{target} = math.lcm({args})"], False
    if line.startswith(("INIT ", "ASSIGN ")):
        return [_strip_assignment_prefix(line)], False
    if line.startswith("AUG "):
        return [line[4:].strip()], False
    if line.startswith("EXPR "):
        return [line[5:].strip()], False
    if line.startswith("STMT "):
        return [line[5:].strip()], False
    if line.startswith("RETURN "):
        return [_compile_return(line[7:].strip())], False
    return [], False


def _compile_return(expr: str) -> str:
    op_call = re.match(r"^(MEAN|SUM|COUNT|SORT|MIN|MAX|GCD|LCM)\((.*)\)$", expr, flags=re.IGNORECASE)
    if not op_call:
        return f"return {expr}"
    op = op_call.group(1).upper()
    args = op_call.group(2).strip()
    if op == "MEAN":
        return f"return (sum({args}) / len({args})) if {args} else 0"
    if op == "SUM":
        return f"return sum({args})"
    if op == "COUNT":
        return f"return len({args})"
    if op == "SORT":
        return f"return sorted({args})"
    if op == "MIN":
        return f"return min({args})"
    if op == "MAX":
        return f"return max({args})"
    if op == "GCD":
        return f"return math.gcd({args})"
    if op == "LCM":
        return f"return math.lcm({args})"
    return f"return {expr}"


def _compile_filter(line: str) -> str:
    match = re.match(
        r"FILTER\s+(.+?)\s*=\s*(.+?)\s+AS\s+(.+?)\s+WHERE\s+(.+)$",
        line,
        flags=re.IGNORECASE,
    )
    if match:
        target, source, element, condition = [part.strip() for part in match.groups()]
        return f"{target} = [{element} for {element} in {source} if {condition}]"
    match = re.match(r"FILTER\s+(.+?)\s*=\s*(.+?)\s+WHERE\s+(.+)$", line, flags=re.IGNORECASE)
    if match:
        target, source, condition = [part.strip() for part in match.groups()]
        element = _first_name(condition) or "item"
        return f"{target} = [{element} for {element} in {source} if {condition}]"
    return "pass"


def _parse_op_assignment(line: str, op: str) -> tuple[str, str]:
    match = re.match(rf"{op}\s+(.+?)\s*=\s*(.+)$", line, flags=re.IGNORECASE)
    if not match:
        return "result", "[]"
    return match.group(1).strip(), match.group(2).strip()


def _parse_op_args_assignment(line: str, op: str) -> tuple[str, str]:
    target, args = _parse_op_assignment(line, op)
    return target, args


def _strip_assignment_prefix(line: str) -> str:
    return re.sub(r"^(INIT|ASSIGN)\s+", "", line, flags=re.IGNORECASE).strip()


def _parse_func(line: str) -> tuple[str, list[str]]:
    match = re.match(r"FUNC\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*$", line)
    if not match:
        return "solution", []
    params = [_safe_identifier(part.strip(), "arg") for part in match.group(2).split(",") if part.strip()]
    return match.group(1), _dedupe(params)


def _needs_math(lines: list[str]) -> bool:
    pattern = re.compile(r"\b(GCD|LCM)\b|\b(math\.gcd|math\.lcm)\b", flags=re.IGNORECASE)
    return any(pattern.search(line) for line in lines)


def _listcomp_filter_parts(node: ast.AST) -> tuple[str, str, str] | None:
    if not isinstance(node, ast.ListComp) or len(node.generators) != 1:
        return None
    generator = node.generators[0]
    if not generator.ifs:
        return None
    element = _unparse(generator.target) or "item"
    source = _unparse(generator.iter) or "values"
    condition = " and ".join(_unparse(cond) for cond in generator.ifs if _unparse(cond))
    if not condition:
        return None
    return element, source, condition


def _mean_source(node: ast.AST) -> str | None:
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return None
    left = _call_info(node.left)
    right = _call_info(node.right)
    if left and right and left[0] == "sum" and right[0] == "len" and left[1] == right[1] and left[1]:
        return left[1][0]
    return None


def _call_info(node: ast.AST | None) -> tuple[str, list[str]] | None:
    if not isinstance(node, ast.Call):
        return None
    name = _call_name(node)
    args = [_unparse(arg) for arg in node.args]
    return name, [arg for arg in args if arg]


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id.lower()
    if isinstance(func, ast.Attribute):
        return func.attr.lower()
    return ""


def _first_function(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return stmt
    return None


def _infer_params_from_input(input_value: Any) -> list[str]:
    text = _clean_text(input_value)
    if not text:
        return []
    names = re.findall(r"\b[a-zA-Z_]\w*\b(?=\s*=)", text)
    if names:
        return _dedupe([_safe_identifier(name, "arg") for name in names])
    return ["input_value"]


def _fallback_ir(instruction: str, input_text: str, reason: str) -> AlgorithmIR:
    lower = instruction.lower()
    lines = ["FUNC solution(input_value)"]
    if any(word in lower for word in ("negative", "positive", "even", "odd", "filter")):
        lines.append("FILTER selected = input_value AS item WHERE requested_condition(item)")
    if "average" in lower or "mean" in lower:
        lines.append("RETURN MEAN(selected)")
    elif "sum" in lower or "total" in lower:
        lines.append("RETURN SUM(selected)")
    elif "count" in lower:
        lines.append("RETURN COUNT(selected)")
    elif "gcd" in lower or "hcf" in lower:
        lines.append("RETURN GCD(input_value)")
    elif "lcm" in lower:
        lines.append("RETURN LCM(input_value)")
    else:
        lines.append("RETURN input_value")
    return AlgorithmIR(
        lines=lines,
        confidence=0.35,
        metadata={"source": "keyword_typed_ir_fallback", "parse_ok": False, "reason": reason, "input": input_text},
    )


def _targets_text(targets: list[ast.expr]) -> str:
    text = ", ".join(_unparse(target) for target in targets)
    return text or "result"


def _op_symbol(op: ast.operator) -> str:
    return {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "//",
        ast.Mod: "%",
        ast.Pow: "**",
    }.get(type(op), "+")


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node).strip()
    except Exception:
        return node.__class__.__name__


def _first_name(text: str) -> str | None:
    match = re.search(r"\b[A-Za-z_]\w*\b", text)
    return match.group(0) if match else None


def _clean_code(value: Any) -> str:
    text = "" if value is None else str(value)
    return textwrap.dedent(text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _clean_line(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def _safe_identifier(text: str, fallback: str) -> str:
    text = re.sub(r"\W+", "_", str(text).strip()).strip("_")
    if not text or text[0].isdigit() or keyword.iskeyword(text):
        return fallback
    return text


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}_{count + 1}")
    return result


def _has_executable_line(lines: list[str]) -> bool:
    return any(line.strip() and not line.strip().startswith("#") for line in lines)
