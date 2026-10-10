"""Generate solution code from a decoded semantic state/data-flow graph.

The primary path in this module is a deterministic graph-to-Python compiler:

    predicted graph latent -> decoded graph JSON -> Python code

That keeps the final answer downstream of the graph instead of letting a code LLM
solve the original problem again. A frozen LLM generator is still kept as an
optional debugging/upper-bound helper, but the Kaggle notebook uses the symbolic
compiler by default.
"""

from __future__ import annotations

import ast
import json
import keyword
import re
from collections import defaultdict
from typing import Any

from .embedding import _disable_optional_vision_imports


DEFAULT_CODEGEN_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
CONTROL_EDGE_TYPES = {"next", "loop_body", "true_branch", "false_branch", "exit"}
OPERATION_NODE_TYPES = {
    "INITIALIZE",
    "ITERATE",
    "CONDITION",
    "UPDATE",
    "RETURN",
    "SORT",
    "SEARCH",
    "COUNT",
    "ACCUMULATE",
}
KNOWN_CALL_NAMES = {
    "abs",
    "all",
    "any",
    "bool",
    "chr",
    "dict",
    "enumerate",
    "filter",
    "float",
    "format",
    "int",
    "len",
    "list",
    "map",
    "max",
    "min",
    "ord",
    "pow",
    "print",
    "range",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
}

# Cache loaded (model, tokenizer, device) per checkpoint so repeated calls are cheap.
_CODEGEN_CACHE: dict[str, Any] = {}


def _load_codegen_model(model_name: str, device: str | None = None) -> tuple[Any, Any, Any]:
    if model_name in _CODEGEN_CACHE:
        return _CODEGEN_CACHE[model_name]

    _disable_optional_vision_imports()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device_obj = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    dtype = torch.float16 if device_obj.type == "cuda" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype).to(device_obj)
    model.eval()
    # Clear sampling defaults so greedy decoding does not emit temperature/top_p warnings.
    gen_cfg = model.generation_config
    gen_cfg.do_sample = False
    gen_cfg.temperature = None
    gen_cfg.top_p = None
    gen_cfg.top_k = None
    _CODEGEN_CACHE[model_name] = (model, tokenizer, device_obj)
    return _CODEGEN_CACHE[model_name]


def graph_to_readable(graph_json: str) -> str:
    """Render canonical graph JSON as a compact, LLM-friendly node/edge listing."""
    try:
        graph = json.loads(graph_json)
    except (ValueError, TypeError):
        return str(graph_json)

    lines = ["Nodes:"]
    for node in graph.get("nodes", []):
        lines.append(f"  [{node.get('id')}] {node.get('type')}: {node.get('label')}")
    lines.append("Edges:")
    for edge in graph.get("edges", []):
        lines.append(f"  {edge.get('source')} --{edge.get('type')}--> {edge.get('target')}")
    return "\n".join(lines)


def _extract_code_block(text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def generate_code_from_graph_symbolic(graph_json: str, function_name: str = "solution") -> str:
    """Compile decoded graph JSON into Python without calling any code LLM.

    This is intentionally conservative. It trusts the decoded graph labels as the
    algorithmic program steps and uses the graph's control edges to recover loops,
    branches, and fall-through order. If the decoded graph is wrong, the emitted
    code will also be wrong; that is exactly the dependency we want to inspect.
    """

    graph = _load_graph(graph_json)
    nodes = _nodes_by_id(graph)
    control = _control_successors(graph)
    params = _extract_parameters(graph, nodes)
    start_id = _entry_node_id(nodes, control)
    safe_function_name = _safe_identifier(function_name, fallback="solution")

    emitter = _GraphCodeEmitter(nodes, control, function_name=safe_function_name)
    body = emitter.emit_sequence(start_id, indent=1) if start_id is not None else []
    if not _has_executable_line(body):
        body = ["    return None"]

    header = f"def {safe_function_name}({', '.join(params)}):"
    return "\n".join([header, *body])


def generate_code_from_graph(
    graph_json: str,
    problem_text: str = "",
    include_problem: bool = False,
    model_name: str = DEFAULT_CODEGEN_MODEL,
    max_new_tokens: int = 320,
    device: str | None = None,
) -> str:
    """Turn a state/data-flow graph into Python code with a frozen code LLM.

    This helper is optional. For the core JEPA experiment use
    :func:`generate_code_from_graph_symbolic`, which does not load Qwen or any
    other code generation model.
    """

    import torch

    model, tokenizer, device_obj = _load_codegen_model(model_name, device=device)
    graph_view = graph_to_readable(graph_json)

    if include_problem and problem_text:
        system = (
            "You are an expert Python developer. Use the problem statement as the task contract "
            "and the semantic state/data-flow graph as the algorithmic plan. The graph may be "
            "imperfect because it was predicted by a model, so preserve the problem semantics if "
            "there is a conflict. Output ONLY one ```python code block, with no explanation."
        )
        user = (
            f"Problem:\n{problem_text}\n\n"
            f"Predicted algorithm state/data-flow graph:\n{graph_view}\n\n"
            "Write the Python solution."
        )
    else:
        system = (
            "You are an expert Python developer. You are given ONLY a semantic state/data-flow "
            "graph that fully specifies an algorithm (operation nodes; control-transition edges "
            "next/loop_body/true_branch/false_branch/exit; and data-flow edges reads/writes/returns). "
            "Implement EXACTLY the algorithm encoded by this graph. Do not add behaviour that is not "
            "present in the graph. Output ONLY one ```python code block, with no explanation."
        )
        user = f"Algorithm state/data-flow graph:\n{graph_view}\n\nWrite the Python solution for this graph."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(device_obj)
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    new_tokens = generated[0][inputs["input_ids"].shape[1]:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return _extract_code_block(text)


class _GraphCodeEmitter:
    def __init__(
        self,
        nodes: dict[int, dict[str, Any]],
        control: dict[int, dict[str, list[int]]],
        function_name: str,
    ) -> None:
        self.nodes = nodes
        self.control = control
        self.function_name = function_name

    def emit_sequence(
        self,
        start_id: int | None,
        indent: int = 1,
        stop_ids: set[int] | None = None,
        stack: tuple[int, ...] = (),
    ) -> list[str]:
        lines: list[str] = []
        current = start_id
        stop_ids = set(stop_ids or set())
        local_seen: set[int] = set()

        while current is not None:
            if current in stop_ids or current in local_seen or current in stack:
                break
            node = self.nodes.get(current)
            if node is None:
                break
            if not _is_operation_node(node):
                current = self._continuation(current, stop_ids, local_seen)
                continue

            local_seen.add(current)
            emitted, terminal = self.emit_node(current, indent=indent, stop_ids=stop_ids, stack=stack)
            lines.extend(emitted)
            if terminal:
                break
            current = self._continuation(current, stop_ids, local_seen)

        return lines

    def emit_node(
        self,
        node_id: int,
        indent: int,
        stop_ids: set[int],
        stack: tuple[int, ...],
    ) -> tuple[list[str], bool]:
        node = self.nodes[node_id]
        node_type = str(node.get("type", "")).upper()
        label = _clean_label(node.get("label", ""))
        prefix = "    " * indent

        if node_type == "ITERATE":
            header = _loop_header(label)
            body_start = self._first_successor(node_id, "loop_body")
            body = self.emit_sequence(
                body_start,
                indent=indent + 1,
                stop_ids=stop_ids | {node_id},
                stack=stack + (node_id,),
            )
            if not _has_executable_line(body):
                body = ["    " * (indent + 1) + "pass"]
            return [prefix + header, *body], False

        if node_type == "CONDITION":
            condition = _condition_expr(label)
            true_start = self._first_successor(node_id, "true_branch")
            false_start = self._first_successor(node_id, "false_branch")
            true_body = self.emit_sequence(
                true_start,
                indent=indent + 1,
                stop_ids=stop_ids | {node_id},
                stack=stack + (node_id,),
            )
            if not _has_executable_line(true_body):
                true_body = ["    " * (indent + 1) + "pass"]

            lines = [prefix + f"if {condition}:", *true_body]
            if false_start is not None:
                false_body = self.emit_sequence(
                    false_start,
                    indent=indent + 1,
                    stop_ids=stop_ids | {node_id},
                    stack=stack + (node_id,),
                )
                if not _has_executable_line(false_body):
                    false_body = ["    " * (indent + 1) + "pass"]
                lines.extend([prefix + "else:", *false_body])
            return lines, False

        if node_type == "RETURN":
            statement, terminal = _return_statement(label, self.function_name)
            return [prefix + statement], terminal

        statement = _operation_statement(label)
        if statement is None:
            return [], False
        return [prefix + statement], False

    def _continuation(self, node_id: int, stop_ids: set[int], seen: set[int]) -> int | None:
        node = self.nodes.get(node_id, {})
        node_type = str(node.get("type", "")).upper()
        edge_order = ["exit", "next"] if node_type == "ITERATE" else ["next", "exit"]
        for edge_type in edge_order:
            successor = self._first_successor(node_id, edge_type, excluded=stop_ids | seen)
            if successor is not None:
                return successor
        return None

    def _first_successor(
        self,
        node_id: int,
        edge_type: str,
        excluded: set[int] | None = None,
    ) -> int | None:
        excluded = excluded or set()
        for target in self.control.get(node_id, {}).get(edge_type, []):
            if target not in excluded and target in self.nodes:
                return target
        return None


def _load_graph(graph_json: str) -> dict[str, Any]:
    # Fast path: the decoder emitted clean, complete JSON.
    try:
        parsed = json.loads(graph_json)
        if isinstance(parsed, dict):
            parsed.setdefault("nodes", [])
            parsed.setdefault("edges", [])
            return parsed
    except (TypeError, ValueError):
        pass
    # Tolerant recovery: the decoder can truncate (hit max_new_tokens) or append junk,
    # leaving the outer JSON invalid. Recover whatever complete node/edge objects exist
    # so a nearly-correct graph still compiles instead of collapsing to an empty body.
    text = str(graph_json)
    return {
        "nodes": _extract_array_objects(text, "nodes"),
        "edges": _extract_array_objects(text, "edges"),
    }


def _extract_array_objects(text: str, key: str) -> list[dict[str, Any]]:
    """Recover complete ``{...}`` objects inside a ``"key": [ ... ]`` array.

    String-aware (ignores braces inside string literals) and tolerant of a missing
    closing bracket, so a truncated graph still yields the objects decoded so far.
    """
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[', text)
    if not match:
        return []
    objects: list[dict[str, Any]] = []
    depth = 0
    start: int | None = None
    in_str = False
    escaped = False
    i = match.end()
    while i < len(text):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            objects.append(obj)
                    except ValueError:
                        pass
                    start = None
        elif ch == "]" and depth == 0:
            break
        i += 1
    return objects


def _nodes_by_id(graph: dict[str, Any]) -> dict[int, dict[str, Any]]:
    nodes: dict[int, dict[str, Any]] = {}
    for raw_node in graph.get("nodes", []):
        if not isinstance(raw_node, dict):
            continue
        try:
            node_id = int(raw_node.get("id"))
        except (TypeError, ValueError):
            continue
        nodes[node_id] = raw_node
    return nodes


def _control_successors(graph: dict[str, Any]) -> dict[int, dict[str, list[int]]]:
    control: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for raw_edge in graph.get("edges", []):
        if not isinstance(raw_edge, dict) or raw_edge.get("type") not in CONTROL_EDGE_TYPES:
            continue
        try:
            source = int(raw_edge.get("source"))
            target = int(raw_edge.get("target"))
        except (TypeError, ValueError):
            continue
        control[source][str(raw_edge["type"])].append(target)
    return control


def _entry_node_id(nodes: dict[int, dict[str, Any]], control: dict[int, dict[str, list[int]]]) -> int | None:
    input_ids = [node_id for node_id, node in sorted(nodes.items()) if str(node.get("type", "")).upper() == "INPUT"]
    for input_id in input_ids:
        for target in control.get(input_id, {}).get("next", []):
            if _is_operation_node(nodes.get(target, {})):
                return target
    for node_id, node in sorted(nodes.items()):
        if _is_operation_node(node):
            return node_id
    return None


def _extract_parameters(graph: dict[str, Any], nodes: dict[int, dict[str, Any]]) -> list[str]:
    for node in nodes.values():
        if str(node.get("type", "")).upper() != "INPUT":
            continue
        label = _clean_label(node.get("label", ""))
        match = re.search(r"function inputs:\s*(.*)", label, flags=re.IGNORECASE)
        if match:
            params = [_safe_identifier(part.strip(), fallback="arg") for part in match.group(1).split(",")]
            params = [param for param in params if param]
            if params:
                return _dedupe_names(params)

    written_data: list[str] = []
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict) or edge.get("type") != "writes":
            continue
        source_node = nodes.get(_safe_int(edge.get("source")))
        target_node = nodes.get(_safe_int(edge.get("target")))
        if not source_node or not target_node:
            continue
        if str(source_node.get("type", "")).upper() == "INPUT" and str(target_node.get("type", "")).upper() == "DATA":
            written_data.append(_safe_identifier(_clean_label(target_node.get("label", "")), fallback="arg"))

    if written_data:
        return _dedupe_names(written_data)
    return []


def _is_operation_node(node: dict[str, Any]) -> bool:
    return str(node.get("type", "")).upper() in OPERATION_NODE_TYPES


def _loop_header(label: str) -> str:
    header = label.rstrip(":")
    if not header.startswith(("for ", "while ")):
        header = "for item in values"
    return header + ":"


def _condition_expr(label: str) -> str:
    condition = label.strip()
    if condition.startswith("if "):
        condition = condition[3:]
    condition = condition.rstrip(":").strip()
    return condition if _is_valid_expr(condition) else "bool(" + repr(condition) + ")"


def _return_statement(label: str, function_name: str) -> tuple[str, bool]:
    if not label:
        return "return None", True
    if label.startswith("return "):
        expr = label[len("return ") :].strip()
        return "return " + _rewrite_recursive_return_expr(expr, function_name), True
    if _is_print_call_label(label):
        return label, False
    if _is_valid_expr(label):
        return f"return {_rewrite_recursive_return_expr(label, function_name)}", True
    return "return " + repr(label), True


def _rewrite_recursive_return_expr(expr_text: str, function_name: str) -> str:
    """Rewrite likely self-recursive calls to the generated function name.

    Target graphs preserve labels from source code. A GCD graph may therefore
    contain ``gcd(b, a % b)`` while the emitted function is named
    ``solution_a_retrieved``. Unknown direct calls in RETURN expressions are
    usually self/helper recursion in this dataset; known builtins and attribute
    calls such as ``math.gcd`` are left alone.
    """

    try:
        tree = ast.parse(expr_text, mode="eval")
    except SyntaxError:
        return expr_text

    class RecursiveCallRewriter(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.AST:
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id not in KNOWN_CALL_NAMES:
                node.func.id = function_name
            return node

    rewritten = RecursiveCallRewriter().visit(tree)
    ast.fix_missing_locations(rewritten)
    try:
        return ast.unparse(rewritten)
    except Exception:
        return expr_text


def _operation_statement(label: str) -> str | None:
    if not label or _is_string_literal_statement(label):
        return None
    if label.startswith(("for ", "while ", "if ")):
        return "pass"
    if _is_valid_statement(label):
        return label
    return "pass"


def _is_valid_statement(text: str) -> bool:
    try:
        ast.parse(text)
    except SyntaxError:
        return False
    return True


def _is_valid_expr(text: str) -> bool:
    try:
        ast.parse(text, mode="eval")
    except SyntaxError:
        return False
    return True


def _is_string_literal_statement(text: str) -> bool:
    try:
        module = ast.parse(text)
    except SyntaxError:
        return False
    return (
        len(module.body) == 1
        and isinstance(module.body[0], ast.Expr)
        and isinstance(module.body[0].value, ast.Constant)
        and isinstance(module.body[0].value.value, str)
    )


def _is_print_call_label(text: str) -> bool:
    try:
        expr = ast.parse(text, mode="eval").body
    except SyntaxError:
        return False
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "print"
    )


def _has_executable_line(lines: list[str]) -> bool:
    return any(line.strip() and not line.strip().startswith("#") for line in lines)


def _safe_identifier(text: str, fallback: str) -> str:
    text = re.sub(r"\W+", "_", text.strip())
    text = text.strip("_")
    if not text or text[0].isdigit() or keyword.iskeyword(text):
        text = fallback
    return text


def _dedupe_names(names: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        base = name
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")
    return result


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_label(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
