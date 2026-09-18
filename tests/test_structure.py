import ast
import importlib
import pkgutil
import unittest
from pathlib import Path

import ggraft


class TestPackage(unittest.TestCase):
    def test_every_module_imports(self):
        # catches syntax errors in modules no other test imports
        found = []
        for info in pkgutil.walk_packages(ggraft.__path__, prefix="ggraft."):
            importlib.import_module(info.name)
            found.append(info.name)
        self.assertIn("ggraft.patching.engine", found)
        self.assertIn("ggraft.glsl.preprocessor", found)
        self.assertIn("ggraft.cli.commands.build", found)


class TestLayering(unittest.TestCase):
    ALLOWED = {
        "__main__": {"cli"},
        "cli": {"patching", "sources", "config", "errors"},
        "patching": {"glsl", "config", "errors"},
        "sources": {"errors"},
        "config": {"errors"},
        "glsl": set(),
        "errors": set(),
    }

    @staticmethod
    def _graph():
        root = Path(ggraft.__file__).parent
        edges = {}
        for file in sorted(root.rglob("*.py")):
            rel = file.relative_to(root)
            group = rel.parts[0] if len(rel.parts) > 1 else rel.stem
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if not node.module or not node.module.startswith("ggraft"):
                    continue
                parts = node.module.split(".")
                names = [parts[1]] if len(parts) > 1 else [a.name for a in node.names]
                for name in names:
                    if name != group and not name.startswith("_"):
                        edges.setdefault(group, set()).add(name)
        return edges

    def test_no_module_imports_outside_its_layer(self):
        for group, deps in self._graph().items():
            self.assertIn(group, self.ALLOWED, f"unknown submodule {group}")
            unexpected = deps - self.ALLOWED[group]
            self.assertFalse(unexpected, f"{group} must not import {sorted(unexpected)}")

    def test_dependency_graph_is_acyclic(self):
        edges = self._graph()
        visiting, done = set(), set()

        def visit(node, trail):
            if node in done:
                return
            self.assertNotIn(node, visiting, f"import cycle: {' -> '.join(trail + [node])}")
            visiting.add(node)
            for nxt in sorted(edges.get(node, ())):
                visit(nxt, trail + [node])
            visiting.discard(node)
            done.add(node)

        for start in sorted(edges):
            visit(start, [])
