"""18 parçası: vision çıktıları için Markdown üretimi ve güvenli görüntüleme."""

import subprocess
from pathlib import Path


def test_vision_prompts_request_markdown():
    from routes.chat import ATTACHMENT_PROMPT
    from routes.rag import RAG_FILE_PROMPT
    from routes.uploads import UPLOAD_EXTRACT_PROMPT
    from services.vision import DEFAULT_PROMPT

    for prompt in (ATTACHMENT_PROMPT, RAG_FILE_PROMPT, UPLOAD_EXTRACT_PROMPT, DEFAULT_PROMPT):
        assert "Markdown" in prompt


def test_markdown_renderer_syntax_and_safe_output():
    root = Path(__file__).resolve().parent.parent
    script = r"""
const assert = require('assert');
global.window = {};
require(process.argv[1]);
const html = window.MedicalMarkdown.render('# Başlık\n\n**Kalın**\n\n| Metrik | Değer |\n|---|---|\n| Sistolik | 117 |\n\n<script>alert(1)</script>');
assert(html.includes('<h1>Başlık</h1>'));
assert(html.includes('<strong>Kalın</strong>'));
assert(html.includes('<table>'));
assert(html.includes('<td>117</td>'));
assert(!html.includes('<script>'));
assert(html.includes('&lt;script&gt;'));
"""
    result = subprocess.run(
        ["node", "-e", script, str(root / "static" / "markdown.js")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()[:500]
