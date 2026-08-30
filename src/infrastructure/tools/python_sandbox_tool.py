"""In-memory isolated Python math and data computation sandbox with execution timeout."""

import ast
import asyncio
import collections
import contextlib
import datetime
import decimal
import fractions
import functools
import io
import itertools
import json
import math
import random
import re
import statistics
from typing import Any, Dict, Optional
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult

SAFE_MODULES = {
    "math": math,
    "statistics": statistics,
    "json": json,
    "random": random,
    "datetime": datetime,
    "re": re,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
    "decimal": decimal,
    "fractions": fractions,
}

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    mod_root = name.split(".")[0]
    if mod_root in SAFE_MODULES:
        return SAFE_MODULES[mod_root]
    raise ImportError(f"Importing module '{name}' is prohibited in sandbox.")


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "dir": dir,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "None": None,
    "True": True,
    "False": False,
    "__import__": _safe_import,
}


BLOCKED_CALLS = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "breakpoint",
    "input",
    "exit",
    "quit",
    "help",
}

BLOCKED_ATTRIBUTES = {
    "__subclasses__",
    "__bases__",
    "__mro__",
    "__class__",
    "__globals__",
    "__code__",
    "__closure__",
    "__builtins__",
    "__import__",
    "__dict__",
}


class SecurityError(Exception):
    pass


class CodeSafetyValidator(ast.NodeVisitor):
    """AST validator that enforces sandbox boundaries and blocks prohibited imports/calls/dunders."""

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            base_mod = alias.name.split(".")[0]
            if base_mod not in SAFE_MODULES:
                raise SecurityError(f"Security Violation: Import of module '{alias.name}' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = (node.module or "").split(".")[0]
        if mod not in SAFE_MODULES:
            raise SecurityError(f"Security Violation: Import from module '{node.module}' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            raise SecurityError(f"Security Violation: Call to function '{node.func.id}()' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in BLOCKED_ATTRIBUTES:
            raise SecurityError(f"Security Violation: Access to attribute '{node.attr}' is prohibited in sandbox.")
        self.generic_visit(node)


class LoopGuardTransformer(ast.NodeTransformer):
    """Inject iteration limit checks into loop bodies to prevent infinite loops."""

    def visit_While(self, node: ast.While):
        self.generic_visit(node)
        guard = ast.Expr(value=ast.Call(func=ast.Name(id="_check_loop_limit", ctx=ast.Load()), args=[], keywords=[]))
        node.body.insert(0, guard)
        return node

    def visit_For(self, node: ast.For):
        self.generic_visit(node)
        guard = ast.Expr(value=ast.Call(func=ast.Name(id="_check_loop_limit", ctx=ast.Load()), args=[], keywords=[]))
        node.body.insert(0, guard)
        return node


def execute_sandboxed_code(code_str: str) -> Dict[str, Any]:
    """Execute python snippet within isolated scope and capture output."""
    code_trimmed = code_str.strip()

    # If code is a single expression, wrap it or evaluate it directly
    tree = None
    is_eval_expr = False
    try:
        tree = ast.parse(code_trimmed, mode="eval")
        is_eval_expr = True
    except SyntaxError:
        tree = ast.parse(code_trimmed, mode="exec")

    validator = CodeSafetyValidator()
    validator.visit(tree)

    if not is_eval_expr:
        transformer = LoopGuardTransformer()
        tree = transformer.visit(tree)
        ast.fix_missing_locations(tree)

    loop_counter = [0]
    max_loops = 100000

    def _check_loop_limit():
        loop_counter[0] += 1
        if loop_counter[0] > max_loops:
            raise TimeoutError("Execution Timed Out: loop iteration limit exceeded (infinite loop protection).")

    sandbox_globals: Dict[str, Any] = {
        "__builtins__": {**SAFE_BUILTINS, "_check_loop_limit": _check_loop_limit},
        "_check_loop_limit": _check_loop_limit,
        **SAFE_MODULES,
    }
    sandbox_locals: Dict[str, Any] = {}


    stdout_capture = io.StringIO()

    if is_eval_expr:
        compiled = compile(tree, filename="<sandbox>", mode="eval")
        with contextlib.redirect_stdout(stdout_capture):
            result_val = eval(compiled, sandbox_globals, sandbox_locals)
        return {
            "stdout": stdout_capture.getvalue().strip(),
            "result": result_val,
            "locals": {}
        }
    else:
        # If the last statement is an expression statement, capture its value
        last_expr_code = None
        if isinstance(tree, ast.Module) and tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body.pop()
            last_expr_code = compile(ast.Expression(body=last_expr.value), filename="<sandbox_last>", mode="eval")

        compiled = compile(tree, filename="<sandbox>", mode="exec")
        with contextlib.redirect_stdout(stdout_capture):
            exec(compiled, sandbox_globals, sandbox_locals)
            result_val = None
            if last_expr_code is not None:
                # Merge imported modules into locals scope
                eval_globals = {**sandbox_globals, **sandbox_locals}
                result_val = eval(last_expr_code, eval_globals, sandbox_locals)

        printed_output = stdout_capture.getvalue().strip()
        if result_val is None and "result" in sandbox_locals:
            result_val = sandbox_locals["result"]

        return {
            "stdout": printed_output,
            "result": result_val,
            "locals": {k: repr(v) for k, v in sandbox_locals.items() if not k.startswith("_")}
        }


class PythonSandboxTool(BaseTool):
    """Executes math, data manipulation, and Python expressions in an isolated sandbox with timeout."""

    def __init__(self, timeout: float = 5.0, default_timeout: float = 5.0):
        self.timeout = timeout or default_timeout
        self.default_timeout = self.timeout

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="python_sandbox",
            description="Execute Python code safely in an isolated environment for mathematics, statistics, data transformations, or logic. Set variable `result` or `print()` to output.",
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code snippet to execute."
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Maximum execution time in seconds (default: 5.0)."
                    }
                },
                "required": ["code"]
            },
            permission=PermissionLevel.EXECUTE,
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        code_str = arguments.get("code", "").strip()
        if not code_str:
            return ToolResult(content="Code parameter cannot be empty.", is_error=True)

        timeout = float(arguments.get("timeout_seconds", self.timeout))
        timeout = max(0.1, min(timeout, 30.0))

        try:
            res_dict = await asyncio.wait_for(
                asyncio.to_thread(execute_sandboxed_code, code_str),
                timeout=timeout
            )

            stdout = res_dict.get("stdout", "")
            result = res_dict.get("result")
            locals_summary = res_dict.get("locals", {})

            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if result is not None:
                output_parts.append(str(result) if isinstance(result, (int, float, str, bool)) else repr(result))
            elif not stdout and locals_summary:
                output_parts.append("\n".join(f"{k} = {v}" for k, v in locals_summary.items()))

            final_text = "\n".join(output_parts) if output_parts else "Code executed successfully with no output."
            return ToolResult(content=final_text, metadata={"has_result": result is not None})

        except asyncio.TimeoutError:
            return ToolResult(content=f"Execution Timed Out after {timeout} seconds.", is_error=True)
        except SyntaxError as se:
            return ToolResult(content=f"Python Syntax Error (line {se.lineno}): {se.msg}", is_error=True)
        except SecurityError as sec:
            return ToolResult(content=str(sec), is_error=True)
        except Exception as e:
            return ToolResult(content=f"Execution Error ({type(e).__name__}): {str(e)}", is_error=True)
