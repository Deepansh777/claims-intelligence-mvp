"""Schema documentation rendered from the data dictionary."""

import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.services.schema_docs import _pdf_text, parse, runs

MD = """# Title

Intro line one
continues here.

## 1. Rules

1. **Bold** first.
2. Second with `code`.

| A | B |
|---|---|
| `x` | **`y`** |

```sql
SELECT 1
```
---
- bullet
#not-a-heading
"""


def test_parse_blocks():
    assert parse(MD) == [
        ("heading", (1, "Title")),
        ("para", "Intro line one continues here."),
        ("heading", (2, "1. Rules")),
        ("list", (True, ["**Bold** first.", "Second with `code`."])),
        ("table", [["A", "B"], ["`x`", "**`y`**"]]),
        ("code", "SELECT 1"),
        ("list", (False, ["bullet"])),
        ("para", "#not-a-heading"),
    ]


def test_inline_runs():
    assert runs("a **b `c`** `d`") == [
        ("a ", False, False),
        ("b ", True, False),
        ("c", True, True),
        (" ", False, False),
        ("d", False, True),
    ]


def test_pdf_text_never_fails_on_unicode():
    assert _pdf_text("a → b − c — d ✓") == "a -> b - c — d ?"


def test_downloads():
    client = TestClient(app)
    docx = client.get("/api/v1/explorer/docs/schema.docx")
    assert docx.status_code == 200 and "attachment" in docx.headers["content-disposition"]
    xml = zipfile.ZipFile(io.BytesIO(docx.content)).read("word/document.xml").decode()
    assert "raw.claims" in xml and "mart.access_hedis_measure" in xml and "ref.drg" in xml

    pdf = client.get("/api/v1/explorer/docs/schema.pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert client.get("/api/v1/explorer/docs/schema.txt").status_code == 422
