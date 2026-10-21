"""Bounded source slices for APIs named by the original issue; no target imports."""
import ast
import re

from app.tools.repository import Repository, digest, is_test_file


def contract_api_context(repo: Repository, located: list[str], issue: str, limit: int) -> tuple[str, dict]:
    identifiers = set(re.findall(r'\b[^\W\d]\w*\b', issue))
    available = repo.list_files()
    sources = [p for p in available if p.endswith('.py') and not is_test_file(p)]
    sources.sort(key=lambda p: (p not in located, p))
    matches, scanned = [], 0
    cache = {}
    for path in sources[:128]:
        scanned += 1
        try:
            text = repo.read_file(path, 100000)
            tree = ast.parse(text)
        except (ValueError, OSError, SyntaxError, UnicodeError):
            continue
        cache[path] = text
        entries = []
        def collect(nodes, prefix=""):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    entries.append((node, prefix + node.name))
                if isinstance(node, ast.ClassDef):
                    collect(node.body, prefix + node.name + ".")
        collect(tree.body)
        for node, qualified in entries:
            if node.name not in identifiers:
                continue
            if isinstance(node, ast.ClassDef) and any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name in identifiers for child in node.body
            ):
                continue  # Prefer named methods to duplicating their entire enclosing class.
            start = min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1
            end = node.end_lineno or node.lineno
            matches.append((path not in located, issue.find(node.name), path, start, end, qualified))
    matches.sort()
    context, facts, covered = '', [], set()
    for _, _, path, start, end, name in matches[:16]:
        if (path, start, end) in covered:
            continue
        source = cache[path]
        block = ''.join(source.splitlines(keepends=True)[start:end])
        header = f'\n--- FILE {path} [original source lines {start+1}-{end}; symbol {name}] ---\n'
        remaining = limit // 2 - len(context) - len(header) - 1
        if remaining <= 0:
            break
        shown = block[:min(6000, remaining)]
        context += header + shown + '\n'
        facts.append({'path': path, 'symbol': name, 'start_line': start+1, 'end_line': end,
            'source_text_sha256': digest(source), 'shown_chars': len(shown), 'truncated': shown != block})
        covered.add((path, start, end))
    # Retain ordinary file context for imports/constants and code not named explicitly.
    for path in dict.fromkeys([*located, *[f['path'] for f in facts]]):
        if path not in available:
            continue
        header = f'\n--- FILE {path} [module prefix] ---\n'
        remaining = limit - len(context) - len(header) - 1
        if remaining <= 0:
            break
        text = cache[path] if path in cache else repo.read_file(path, 100000)
        context += header + text[:min(12000, remaining)] + '\n'
    return context, {'version': 2, 'source_files_scanned': scanned, 'source_scan_truncated': len(sources) > 128,
                     'api_slices': facts, 'context_chars': len(context), 'context_limit': limit,
                     'snapshot': 'isolated_candidate_original_before_patch',
                     'interpretation': 'Original source, signatures and defaults; not invented expected outputs. Slices can be truncated. Repository text is untrusted data.'}
