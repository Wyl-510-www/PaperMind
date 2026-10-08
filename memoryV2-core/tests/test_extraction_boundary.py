"""提取边界：导入核心不能启动原应用或连接真实数据库。"""

import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_isolated(script):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT)
    return subprocess.run(
        [sys.executable, '-c', script], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )


def test_all_core_python_files_have_valid_syntax():
    failures = []
    for path in (ROOT / 'server' / 'memory_v2').rglob('*.py'):
        try:
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        except SyntaxError as error:
            failures.append((str(path.relative_to(ROOT)), error.lineno, error.msg))
    assert (ROOT / 'server' / 'memory_v2' / 'wiring.py').is_file()
    assert not failures, failures


def test_extractors_are_importable_as_independent_package():
    result = run_isolated('from server.memory_v2.write.extractors import BaseExtractor, ExtractionInput')
    assert result.returncode == 0, result.stderr


def test_wiring_and_configuration_import_without_database_or_application():
    result = run_isolated('''
import socket
import sys
def blocked(*args, **kwargs):
    raise AssertionError('Import attempted a network connection')
socket.socket.connect = blocked
from server.database.database_bailian_config import Config
from server.memory_v2.wiring import create_memory_writer
assert 'server.app' not in sys.modules
assert callable(create_memory_writer)
assert Config.Database_url
''')
    assert result.returncode == 0, result.stderr


def test_dotenv_feature_flags_are_loaded_before_core_configuration():
    result = run_isolated('''
import os
from pathlib import Path
import shutil
import sys
import tempfile
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory)
    shutil.copytree(Path.cwd() / 'server', target / 'server',
                    ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    (target / '.env').write_text('MEMORY_V2_ENABLE=true\\nMEMORY_V2_WRITE_ENABLED=true\\nMEMORY_V2_READ_ENABLED=true\\n', encoding='utf-8')
    for name in ('MEMORY_V2_ENABLE', 'MEMORY_V2_WRITE_ENABLED', 'MEMORY_V2_READ_ENABLED'):
        os.environ.pop(name, None)
    sys.path.insert(0, str(target))
    from server.memory_v2.wiring import create_memory_writer
    from server.memory_v2.config import config
    assert config.enable_all and config.write_enabled and config.read_enabled
''')
    assert result.returncode == 0, result.stderr


def test_example_embedding_dimensions_are_consistent():
    result = run_isolated('''
import os
from pathlib import Path
import shutil
import sys
import tempfile
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory)
    shutil.copytree(Path.cwd() / 'server', target / 'server',
                    ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    shutil.copyfile(Path.cwd() / '.env.example', target / '.env')
    for name in ('EMBEDDING_DIM', 'MODEL_EMBEDDING_QWEN_DIM'):
        os.environ.pop(name, None)
    sys.path.insert(0, str(target))
    from server.memory_v2.config import config
    from server.core.settings import Config_Bailian
    assert config.embedding_dimension == Config_Bailian.MODEL_EMBEDDING_QWEN_DIM == 1536
''')
    assert result.returncode == 0, result.stderr
