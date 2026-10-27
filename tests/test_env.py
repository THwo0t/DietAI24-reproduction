"""A1: the .venv built from requirements.txt runs every script in code/ (offline)."""
import ast
import importlib
import importlib.metadata
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / 'code'
# Not in env/env.yml: SQLAlchemy needs greenlet on Linux x86_64 but not on the
# authors' macOS arm64 (CHECKLIST.md A1).
NOT_IN_ENV_YML = {'greenlet': '3.0.3'}
# Imported at run time rather than by an import statement in code/.
RUNTIME_IMPORTS = ['chromadb',   # langchain_community.vectorstores.Chroma
                   'openpyxl',   # pandas.read_excel on .xlsx
                   'tiktoken']   # langchain_openai.OpenAIEmbeddings


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def env_yml_pins():
    """Versions in env/env.yml: pip pins, and conda pins for names pip does not list."""
    conda, pip = {}, {}
    section = None
    for line in (ROOT / 'env' / 'env.yml').read_text().splitlines():
        if line.strip() == 'dependencies:':
            section = 'conda'
        elif line.strip() == '- pip:':
            section = 'pip'
        elif section == 'conda' and re.fullmatch(r'  - [^=\s]+=[^=\s]+=\S+', line):
            name, version, _ = line.strip()[2:].split('=')
            conda[normalize(name)] = version
        elif section == 'pip' and re.fullmatch(r'      - \S+==\S+', line):
            name, version = line.strip()[2:].split('==')
            pip[normalize(name)] = version
    return {**conda, **pip}


def top_level_names(path):
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


class TestEnvironment(unittest.TestCase):

    def test_python_version(self):
        self.assertEqual(sys.version_info[:3], (3, 10, 13))

    def test_every_import_in_code_resolves(self):
        # Scripts such as nutrient_estimate.py read data files at module level, so the
        # import statements are resolved one by one instead of importing the scripts.
        local = {p.stem for p in CODE.glob('*.py')}
        for path in sorted(CODE.glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        with self.subTest(script=path.name, module=alias.name):
                            importlib.import_module(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        with self.subTest(script=path.name, module=node.module, name=alias.name):
                            if node.module in local:
                                self.assertIn(alias.name, top_level_names(CODE / f'{node.module}.py'))
                            else:
                                module = importlib.import_module(node.module)
                                if not hasattr(module, alias.name):
                                    importlib.import_module(f'{node.module}.{alias.name}')
        for name in RUNTIME_IMPORTS:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_installed_versions_are_env_yml_versions(self):
        pins = {**env_yml_pins(), **NOT_IN_ENV_YML}
        for dist in importlib.metadata.distributions():
            name = normalize(dist.metadata['Name'])
            with self.subTest(package=name):
                self.assertIn(name, pins)
                self.assertEqual(dist.version, pins[name])

    def test_installed_packages_match_archived_freeze(self):
        archived = {}
        for line in (ROOT / 'env' / 'pip-freeze.txt').read_text().splitlines():
            if line and not line.startswith('#'):
                name, version = line.split('==')
                archived[normalize(name)] = version
        installed = {normalize(d.metadata['Name']): d.version
                     for d in importlib.metadata.distributions()}
        self.assertEqual(installed, archived)

    def test_requirements_are_pinned_to_env_yml(self):
        pins = env_yml_pins()
        for line in (ROOT / 'requirements.txt').read_text().splitlines():
            requirement = line.split('#')[0].strip()
            if requirement:
                name, version = requirement.split('==')
                with self.subTest(package=name):
                    self.assertEqual(version, pins[normalize(name)])


if __name__ == '__main__':
    unittest.main()
