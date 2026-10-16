"""Conservative syntax checks for explicit constructor examples; never execute code.

This detects substitutions such as wrapping an issue's constructor input in another
constructor. It is a coverage precondition, not a semantic proof or a test oracle.
Only short, literal constructor expressions are supported. Other prose contracts
remain the model reviewer's and independent evaluator's responsibility.
"""

import ast
import builtins
import re

from app.models.schemas import Patch

CONSTRUCTORS = {"range", "list", "tuple", "dict", "set", "frozenset", "bytes", "bytearray"}


def literal_input_examples(issue: str) -> list[str]:
    examples = []
    for match in re.finditer(r"\b(" + "|".join(sorted(CONSTRUCTORS)) + r")\s*\(", issue):
        fragment = issue[match.start():match.start() + 512]
        for end, character in enumerate(fragment):
            if character != ")":
                continue
            text = fragment[:end + 1]
            try:
                node = ast.parse(text, mode="eval").body
            except (SyntaxError, ValueError):
                continue
            allowed = (ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant, ast.List,
                       ast.Tuple, ast.Dict, ast.Set, ast.UnaryOp, ast.USub, ast.UAdd, ast.keyword)
            if all(isinstance(item, allowed) for item in ast.walk(node)) and all(
                not isinstance(item, ast.Name) or item.id in CONSTRUCTORS
                for item in ast.walk(node)
            ):
                examples.append(text)
            break
    return list(dict.fromkeys(examples))[:16]


def validate_literal_inputs(
    issue: str, patch: Patch, existing_tests: dict[str, str] | None = None,
) -> None:
    examples = literal_input_examples(issue)
    if not examples:
        return
    observed = set()
    sources = list((existing_tests or {}).values())
    for edit in patch.edits:
        if edit.old or not (
            "tests" in edit.path.replace("\\", "/").split("/")
            or edit.path.rsplit("/", 1)[-1].startswith("test_")
        ):
            continue
        sources.append(edit.new)
    for source in sources:
        tree = ast.parse(source)
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bindings: dict[str, list[ast.AST]] = {}
            for node in ast.walk(function):
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target = node.targets[0]
                    if isinstance(target, ast.Name):
                        bindings.setdefault(target.id, []).append(node.value)
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and hasattr(builtins, node.func.id):
                    continue
                for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                    if isinstance(argument, ast.Name) and len(bindings.get(argument.id, [])) == 1:
                        argument = bindings[argument.id][0]
                    observed.add(ast.dump(argument))
    missing = [example for example in examples
               if ast.dump(ast.parse(example, mode="eval").body) not in observed]
    if missing:
        raise ValueError(
            "Regression tests must pass each literal issue input unchanged to the "
            "function under test: " + ", ".join(missing)
            + ". Wrapping it in another constructor changes the input contract. "
            "Add a NEW test filename; existing tests are immutable."
        )
