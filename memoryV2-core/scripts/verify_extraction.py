"""离线核验来源哈希、提取文件、Python 语法和已知内部导入问题。"""

import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module_path(name):
    path = ROOT.joinpath(*name.split('.'))
    for candidate in (path.with_suffix('.py'), path / '__init__.py'):
        if candidate.is_file():
            return candidate
    return None


def exports(path):
    names = set()
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.asname or a.name.split('.')[0] for a in node.names)
    return names


def find_internal_import_issues():
    issues = []
    for path in sorted((ROOT / 'server').rglob('*.py')):
        if 'tests' in path.relative_to(ROOT).parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        package = list(path.parent.relative_to(ROOT).parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                name = node.module or ''
                if node.level:
                    name = '.'.join(package[:len(package) - node.level + 1] + ([name] if name else []))
                if not name.startswith('server.'):
                    continue
                target = module_path(name)
                if target is None:
                    issues.append({'file': path.relative_to(ROOT).as_posix(), 'line': node.lineno,
                                   'kind': 'missing_module', 'target': name})
                    continue
                available = exports(target)
                for alias in node.names:
                    if alias.name == '*':
                        continue
                    if alias.name not in available and module_path(name + '.' + alias.name) is None:
                        issues.append({'file': path.relative_to(ROOT).as_posix(), 'line': node.lineno,
                                       'kind': 'missing_export', 'target': name + '.' + alias.name})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('server.') and module_path(alias.name) is None:
                        issues.append({'file': path.relative_to(ROOT).as_posix(), 'line': node.lineno,
                                       'kind': 'missing_module', 'target': alias.name})
    return issues


def main():
    manifest = json.loads((ROOT / 'extraction-manifest.json').read_text(encoding='utf-8'))
    source = Path(manifest['source_root'])
    source_checked = 0
    for entry in manifest['entries']:
        path = ROOT / entry['path']
        assert path.is_file(), f"Missing extracted file: {entry['path']}"
        assert digest(path) == entry['extracted_sha256'], f"Changed extracted file: {entry['path']}"
        if not entry['modified']:
            assert entry['source_sha256'] == entry['extracted_sha256'], entry['path']
        if source.is_dir():
            assert digest(source / entry['path']) == entry['source_sha256'], f"Source changed: {entry['path']}"
            source_checked += 1
    for entry in manifest['generated_files']:
        assert digest(ROOT / entry['path']) == entry['sha256'], f"Changed generated file: {entry['path']}"
    python_files = [p for p in ROOT.rglob('*.py') if not any(x in p.parts for x in ('.venv', '__pycache__'))]
    for path in python_files:
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    issues = find_internal_import_issues()
    expected = json.loads((ROOT / 'known-upstream-import-issues.json').read_text(encoding='utf-8'))
    assert issues == expected, 'Internal import issues changed; inspect before updating the baseline'
    assert not (ROOT / '.env').exists(), 'The extraction snapshot should contain .env.example only'
    print(json.dumps({
        'status': 'extraction_integrity_passed',
        'copied_files_verified': len(manifest['entries']),
        'source_files_unchanged': source_checked,
        'generated_files_verified': len(manifest['generated_files']),
        'python_syntax_checked': len(python_files),
        'known_upstream_import_issues': len(issues),
        'runtime_services_tested': False,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, SyntaxError, OSError, ValueError) as error:
        print(f'VERIFICATION FAILED: {error}', file=sys.stderr)
        raise SystemExit(1)
