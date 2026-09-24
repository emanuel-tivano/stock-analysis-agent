import shutil
import subprocess
from pathlib import Path

import pytest


def test_javascript_hitl_interactions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node optional: run node --test tests/web/hitl.test.cjs for UI logic")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "--test", "tests/web/hitl.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hitl_assets_security_and_accessibility():
    root = Path(__file__).resolve().parents[2] / "src/merval_agent/api/web"
    js = (root / "app.js").read_text(encoding="utf-8")
    css = (root / "styles.css").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "localStorage" not in js
    assert "node.textContent = text" in js
    assert '"aria-busy"' in js and '"aria-live", "polite"' in js
    assert ".review-card :focus-visible" in css
    assert "flex-wrap: wrap" in css
    assert 'type = "button"' in js
