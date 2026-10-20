"""Source-bound preparation facts for failed NEW tests; never execute target code."""
import ast
import json

from app.tools.repository import Repository, digest


def preparation_context(repo: Repository, observations: list[dict], limit: int = 6000) -> dict:
    facts = []
    used = 0
    seen = set()
    for observation in observations:
        if observation.get('origin') != 'generated_test':
            continue
        path = observation.get('file', '')
        name = observation.get('test', '').split('[', 1)[0]
        if (path, name) in seen:
            continue
        seen.add((path, name))
        try:
            source = repo.read_file(path, 100000)
            tree = ast.parse(source)
        except (ValueError, OSError, UnicodeError, SyntaxError):
            continue
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.name != name:
                continue
            calls = []
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                arguments = []
                for argument in [*call.args, *(kw.value for kw in call.keywords)][:8]:
                    literal = argument.operand if isinstance(argument, ast.UnaryOp) and isinstance(
                        argument.op, (ast.USub, ast.UAdd)) else argument
                    arguments.append({'expression': ast.unparse(argument)[:160],
                        'literal_type': type(literal.value).__name__ if isinstance(literal, ast.Constant) else 'not_a_literal'})
                calls.append({'line': call.lineno, 'call': ast.unparse(call.func)[:160],
                              'arguments': arguments})
                if len(calls) == 6:
                    break
            block = ''.join(source.splitlines(keepends=True)[function.lineno - 1:function.end_lineno])
            fact = {'file': path, 'test': name, 'source_text_sha256': digest(source),
                'start_line': function.lineno, 'source_excerpt': block[:1200],
                'excerpt_truncated': len(block) > 1200, 'calls': calls,
                'runtime_order_observed': False}
            size = len(json.dumps(fact, ensure_ascii=False))
            if used + size > limit:
                continue
            used += size
            facts.append(fact)
            if len(facts) == 4:
                break
        if len(facts) == 4:
            break
    return {'version': 1, 'facts': facts, 'context_chars': used, 'context_limit': limit,
        'interpretation': 'Untrusted source syntax, not executed call order or proof that the public API was reached. Check fixture construction and literal types, bytes/text encoding, defaults and Unicode expectations against the original issue and source. A setup exception is not a demonstrated functional regression; do not invent expected outputs or weaken justified assertions.'}
