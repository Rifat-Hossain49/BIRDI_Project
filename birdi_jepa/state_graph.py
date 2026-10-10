"""Pseudo-label Python code as canonical semantic algorithm graphs.

The extractor is intentionally deterministic and inspectable. It uses the
reference code only during training-time pseudo-label creation, then serializes
state-transition and data-flow structure as stable JSON for representation
learning. The Python AST is used as a parser, not as the target graph.
"""

from __future__ import annotations

import ast
import json
import re
import textwrap
import warnings
from dataclasses import dataclass, field
from typing import Any, Iterable


NODE_TYPES = {
    "INPUT",
    "INITIALIZE",
    "ITERATE",
    "CONDITION",
    "UPDATE",
    "RETURN",
    "DATA",
    "SORT",
    "SEARCH",
    "COUNT",
    "ACCUMULATE",
}

EDGE_TYPES = {
    "next",
    "loop_body",
    "true_branch",
    "false_branch",
    "exit",
    "reads",
    "writes",
    "returns",
}


@dataclass(frozen=True)
class GraphNode:
    id: int
    type: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "label": self.label}


@dataclass(frozen=True)
class GraphEdge:
    source: int
    target: int
    type: str

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "type": self.type}


@dataclass
class StateGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "confidence": round(float(self.confidence), 4),
            "metadata": self.metadata,
        }

    def to_canonical_json(self) -> str:
        """Return compact, deterministic graph JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class _Tail:
    node_id: int
    edge_to_next: str = "next"


class CodeStateGraphExtractor:
    """Extract a semantic state/data-flow graph from Python reference code.

    This is not an AST target. The AST only lets us parse code deterministically;
    the emitted graph contains operation/state nodes, control-transition edges,
    variable/data nodes, and data-flow edges.
    """

    def __init__(self, max_label_chars: int = 180) -> None:
        self.max_label_chars = max_label_chars
        self._nodes: list[GraphNode] = []
        self._edges: list[GraphEdge] = []
        self._assigned: set[str] = set()
        self._data_nodes: dict[str, int] = {}

    def extract(self, instruction: Any, input_value: Any, code: Any) -> StateGraph:
        instruction_text = _clean_text(instruction)
        input_text = _clean_text(input_value)
        code_text = _clean_code(code)

        if not code_text:
            return self._fallback_graph(instruction_text, input_text, reason="empty_code")

        try:
            # Dataset reference code often contains invalid escape sequences (e.g.
            # unescaped regex strings). Those raise a cosmetic SyntaxWarning on
            # Python 3.12 that floods the logs; suppress it while still parsing.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(code_text)
        except SyntaxError as exc:
            return self._fallback_graph(instruction_text, input_text, reason=f"syntax_error:{exc.msg}")

        self._nodes = []
        self._edges = []
        self._assigned = set()
        self._data_nodes = {}

        root_body = self._select_algorithm_body(tree)
        input_label = self._input_label(tree, instruction_text, input_text)
        input_id = self._add_node("INPUT", input_label)
        self._attach_input_data(tree, input_text, input_id)

        tails = self._walk_statements(root_body, [_Tail(input_id, "next")])
        if not self._has_node_type("RETURN"):
            return_id = self._add_node("RETURN", "result")
            self._connect(tails, return_id)
            self._attach_data_flow(return_id, reads={"result"}, returns={"result"})

        confidence = 0.92 if self._has_control_or_update() else 0.75
        return StateGraph(
            nodes=self._nodes,
            edges=self._dedupe_edges(self._edges),
            confidence=confidence,
            metadata={
                "source": "python_ast_semantic_extractor",
                "graph_kind": "state_transition_plus_data_flow",
                "parse_ok": True,
            },
        )

    def _select_algorithm_body(self, tree: ast.Module) -> list[ast.stmt]:
        functions = [stmt for stmt in tree.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if functions:
            return list(functions[0].body)
        return list(tree.body)

    def _input_label(self, tree: ast.Module, instruction: str, input_text: str) -> str:
        functions = [stmt for stmt in tree.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if functions:
            args = [arg.arg for arg in functions[0].args.args]
            if args:
                return "function inputs: " + ", ".join(args)
        if input_text:
            return "input: " + input_text
        return _truncate(instruction or "problem input", self.max_label_chars)

    def _walk_statements(self, statements: Iterable[ast.stmt], prev: list[_Tail]) -> list[_Tail]:
        tails = prev
        for stmt in statements:
            tails = self._walk_statement(stmt, tails)
        return tails

    def _walk_statement(self, stmt: ast.stmt, prev: list[_Tail]) -> list[_Tail]:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._walk_statements(stmt.body, prev)

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            label = f"for {_safe_unparse(stmt.target)} in {_safe_unparse(stmt.iter)}"
            node_id = self._add_node("ITERATE", label)
            self._connect(prev, node_id)
            self._attach_data_flow(
                node_id,
                reads=_read_names(stmt.iter),
                writes=_target_names(stmt.target),
            )
            body_tails = self._walk_statements(stmt.body, [_Tail(node_id, "loop_body")])
            for tail in body_tails:
                self._add_edge(tail.node_id, node_id, "next")
            orelse_tails = self._walk_statements(stmt.orelse, [_Tail(node_id, "exit")]) if stmt.orelse else [_Tail(node_id, "exit")]
            return orelse_tails

        if isinstance(stmt, ast.While):
            node_id = self._add_node("ITERATE", f"while {_safe_unparse(stmt.test)}")
            self._connect(prev, node_id)
            self._attach_data_flow(node_id, reads=_read_names(stmt.test))
            body_tails = self._walk_statements(stmt.body, [_Tail(node_id, "loop_body")])
            for tail in body_tails:
                self._add_edge(tail.node_id, node_id, "next")
            orelse_tails = self._walk_statements(stmt.orelse, [_Tail(node_id, "exit")]) if stmt.orelse else [_Tail(node_id, "exit")]
            return orelse_tails

        if isinstance(stmt, ast.If):
            node_id = self._add_node("CONDITION", _safe_unparse(stmt.test))
            self._connect(prev, node_id)
            self._attach_data_flow(node_id, reads=_read_names(stmt.test))
            body_tails = self._walk_statements(stmt.body, [_Tail(node_id, "true_branch")])
            else_tails = self._walk_statements(stmt.orelse, [_Tail(node_id, "false_branch")]) if stmt.orelse else [_Tail(node_id, "false_branch")]
            return body_tails + else_tails

        if isinstance(stmt, ast.Return):
            label = _safe_unparse(stmt.value) if stmt.value is not None else "return"
            node_id = self._add_node("RETURN", label)
            self._connect(prev, node_id)
            reads = _read_names(stmt.value)
            self._attach_data_flow(node_id, reads=reads, returns=reads or {"return_value"})
            return [_Tail(node_id, "next")]

        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            node_type = self._classify_assignment(stmt)
            node_id = self._add_node(node_type, _safe_unparse(stmt))
            self._connect(prev, node_id)
            writes = _assigned_names(stmt)
            reads = _assignment_read_names(stmt)
            self._attach_data_flow(node_id, reads=reads, writes=writes)
            self._assigned.update(writes)
            return [_Tail(node_id, "next")]

        if isinstance(stmt, ast.Expr):
            node_type = self._classify_expression(stmt.value)
            node_id = self._add_node(node_type, _safe_unparse(stmt.value))
            self._connect(prev, node_id)
            self._attach_data_flow(
                node_id,
                reads=_read_names(stmt.value),
                writes=_mutated_names(stmt.value),
                returns=_read_names(stmt.value) if _is_print_call(stmt.value) else set(),
            )
            return [_Tail(node_id, "next")]

        if isinstance(stmt, ast.Try):
            node_id = self._add_node("CONDITION", "try / except")
            self._connect(prev, node_id)
            body_tails = self._walk_statements(stmt.body, [_Tail(node_id, "true_branch")])
            handler_tails: list[_Tail] = []
            for handler in stmt.handlers:
                handler_tails.extend(self._walk_statements(handler.body, [_Tail(node_id, "false_branch")]))
            return body_tails + (handler_tails or [_Tail(node_id, "false_branch")])

        if isinstance(stmt, (ast.Break, ast.Continue)):
            node_id = self._add_node("UPDATE", stmt.__class__.__name__.lower())
            self._connect(prev, node_id)
            return [_Tail(node_id, "next")]

        node_id = self._add_node("UPDATE", _safe_unparse(stmt) or stmt.__class__.__name__)
        self._connect(prev, node_id)
        self._attach_data_flow(node_id, reads=_read_names(stmt), writes=_assigned_names(stmt))
        return [_Tail(node_id, "next")]

    def _classify_assignment(self, stmt: ast.stmt) -> str:
        if isinstance(stmt, ast.AugAssign):
            return "ACCUMULATE" if isinstance(stmt.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)) else "UPDATE"

        value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
        if _contains_sort(value):
            return "SORT"
        if _contains_search(value):
            return "SEARCH"
        if _contains_count(value):
            return "COUNT"
        if _contains_accumulate(value):
            return "ACCUMULATE"

        names = _assigned_names(stmt)
        if names and not any(name in self._assigned for name in names):
            return "INITIALIZE"
        return "UPDATE"

    def _classify_expression(self, expr: ast.AST) -> str:
        if _contains_sort(expr):
            return "SORT"
        if _contains_search(expr):
            return "SEARCH"
        if _contains_count(expr):
            return "COUNT"
        if _is_print_call(expr):
            return "RETURN"
        return "UPDATE"

    def _fallback_graph(self, instruction: str, input_text: str, reason: str) -> StateGraph:
        self._nodes = []
        self._edges = []
        input_id = self._add_node("INPUT", _truncate(input_text or instruction or "problem input", self.max_label_chars))
        prev = input_id

        for node_type, label in _keyword_steps(instruction):
            node_id = self._add_node(node_type, label)
            self._add_edge(prev, node_id, "next")
            prev = node_id

        return_id = self._add_node("RETURN", "answer")
        self._add_edge(prev, return_id, "next")
        return StateGraph(
            nodes=self._nodes,
            edges=self._dedupe_edges(self._edges),
            confidence=0.35,
            metadata={
                "source": "keyword_semantic_fallback",
                "graph_kind": "state_transition",
                "parse_ok": False,
                "reason": reason,
            },
        )

    def _add_node(self, node_type: str, label: str) -> int:
        node_type = node_type if node_type in NODE_TYPES else "UPDATE"
        node_id = len(self._nodes)
        self._nodes.append(GraphNode(id=node_id, type=node_type, label=_truncate(label, self.max_label_chars)))
        return node_id

    def _add_edge(self, source: int, target: int, edge_type: str) -> None:
        edge_type = edge_type if edge_type in EDGE_TYPES else "next"
        if source != target:
            self._edges.append(GraphEdge(source=source, target=target, type=edge_type))

    def _connect(self, prev: list[_Tail], target: int) -> None:
        for tail in prev:
            self._add_edge(tail.node_id, target, tail.edge_to_next)

    def _ensure_data_node(self, name: str) -> int:
        name = _clean_text(name)
        if not name:
            name = "value"
        if name not in self._data_nodes:
            self._data_nodes[name] = self._add_node("DATA", name)
        return self._data_nodes[name]

    def _attach_data_flow(
        self,
        operation_id: int,
        reads: set[str] | None = None,
        writes: set[str] | None = None,
        returns: set[str] | None = None,
    ) -> None:
        for name in sorted(reads or set()):
            self._add_edge(self._ensure_data_node(name), operation_id, "reads")
        for name in sorted(writes or set()):
            self._add_edge(operation_id, self._ensure_data_node(name), "writes")
        for name in sorted(returns or set()):
            self._add_edge(operation_id, self._ensure_data_node(name), "returns")

    def _attach_input_data(self, tree: ast.Module, input_text: str, input_id: int) -> None:
        functions = [stmt for stmt in tree.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if functions:
            names = {arg.arg for arg in functions[0].args.args}
        elif input_text:
            names = {"input"}
        else:
            names = set()

        for name in sorted(names):
            self._add_edge(input_id, self._ensure_data_node(name), "writes")

    def _has_node_type(self, node_type: str) -> bool:
        return any(node.type == node_type for node in self._nodes)

    def _has_control_or_update(self) -> bool:
        useful_types = {"ITERATE", "CONDITION", "UPDATE", "SORT", "SEARCH", "COUNT", "ACCUMULATE"}
        return any(node.type in useful_types for node in self._nodes)

    @staticmethod
    def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
        seen: set[tuple[int, int, str]] = set()
        result: list[GraphEdge] = []
        for edge in edges:
            key = (edge.source, edge.target, edge.type)
            if key not in seen:
                seen.add(key)
                result.append(edge)
        return result


def graph_from_code(instruction: Any, input_value: Any, code: Any) -> StateGraph:
    return CodeStateGraphExtractor().extract(instruction, input_value, code)


def build_problem_text(instruction: Any, input_value: Any) -> str:
    instruction_text = _clean_text(instruction)
    input_text = _clean_text(input_value)
    if input_text:
        return f"Problem: {instruction_text}\nInput: {input_text}"
    return f"Problem: {instruction_text}"


def _clean_code(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return textwrap.dedent(text).strip()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, max_chars: int) -> str:
    text = _clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _call_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id.lower()
        if isinstance(func, ast.Attribute):
            return func.attr.lower()
    return ""


def _contains_call_name(node: ast.AST | None, names: set[str]) -> bool:
    if node is None:
        return False
    for child in ast.walk(node):
        if _call_name(child) in names:
            return True
    return False


def _contains_sort(node: ast.AST | None) -> bool:
    return _contains_call_name(node, {"sort", "sorted"})


def _contains_search(node: ast.AST | None) -> bool:
    return _contains_call_name(node, {"find", "index", "search"})


def _contains_count(node: ast.AST | None) -> bool:
    return _contains_call_name(node, {"count", "len"})


def _contains_accumulate(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if _contains_call_name(node, {"sum"}):
        return True
    return any(isinstance(child, ast.BinOp) for child in ast.walk(node))


def _is_print_call(node: ast.AST | None) -> bool:
    return _call_name(node) == "print"


def _read_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.add(child.id)
    return names


def _target_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {_safe_unparse(node)}
    if isinstance(node, ast.Subscript):
        value = _safe_unparse(node.value)
        return {value} if value else set()
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in node.elts:
            names.update(_target_names(item))
        return names
    return set()


def _assignment_read_names(stmt: ast.stmt) -> set[str]:
    if isinstance(stmt, ast.Assign):
        return _read_names(stmt.value)
    if isinstance(stmt, ast.AnnAssign):
        return _read_names(stmt.value)
    if isinstance(stmt, ast.AugAssign):
        return _read_names(stmt.target) | _read_names(stmt.value) | _target_names(stmt.target)
    return set()


def _mutated_names(node: ast.AST | None) -> set[str]:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return set()
    mutating_methods = {
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "update",
    }
    if node.func.attr.lower() not in mutating_methods:
        return set()
    return _target_names(node.func.value)


def _assigned_names(stmt: ast.stmt) -> set[str]:
    targets: list[ast.AST] = []
    if isinstance(stmt, ast.Assign):
        targets = list(stmt.targets)
    elif isinstance(stmt, ast.AnnAssign):
        targets = [stmt.target]
    elif isinstance(stmt, ast.AugAssign):
        targets = [stmt.target]

    names: set[str] = set()
    for target in targets:
        names.update(_target_names(target))
    return names


def _keyword_steps(instruction: str) -> list[tuple[str, str]]:
    lower = instruction.lower()
    steps: list[tuple[str, str]] = []
    if any(word in lower for word in ("list", "array", "string", "tuple", "dictionary", "set")):
        steps.append(("ITERATE", "inspect input elements"))
    if any(word in lower for word in ("if", "even", "odd", "positive", "negative", "filter", "remove", "greater", "less")):
        steps.append(("CONDITION", "apply requested condition"))
    if any(word in lower for word in ("sort", "ascending", "descending", "alphabetical")):
        steps.append(("SORT", "sort values"))
    if any(word in lower for word in ("find", "search", "index", "contains")):
        steps.append(("SEARCH", "search for target value"))
    if "count" in lower or "number of" in lower:
        steps.append(("COUNT", "count matching values"))
    if any(word in lower for word in ("sum", "total", "average", "product", "square")):
        steps.append(("ACCUMULATE", "accumulate computed value"))
    if not steps:
        steps.append(("UPDATE", "compute requested transformation"))
    return steps
