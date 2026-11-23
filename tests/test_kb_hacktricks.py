"""HackTricks importer tests.

Like ``test_kb.py`` these build a tiny fake clone on the fly: the real wiki is
hundreds of megabytes and must never be required for CI.

What must hold, beyond "it imports":

* the licence is treated as CC BY-NC, never as a permissive redistribution;
* every imported document carries an attribution block and our NC notice;
* the upstream ``{{#include}}`` training banner is stripped;
* relative ``.md`` links become in-app reader links;
* images are localised under the configured static root (CSP-safe);
* re-import is idempotent and never overwrites a reviewed body.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_TEST_DATA = tempfile.mkdtemp(prefix="redvault-ht-test-")
os.environ["REDVAULT_DATA"] = _TEST_DATA
os.environ.setdefault("REDVAULT_BOT", "0")
atexit.register(lambda: shutil.rmtree(_TEST_DATA, ignore_errors=True))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.kb_hacktricks import ImageStore, build_body, import_hacktricks, parse_summary  # noqa: E402
from app.kb_models import KB_Document, KB_Source  # noqa: E402
from app.kb_seed import seed_all  # noqa: E402
from app.main import app  # noqa: E402

BANNER = "> Learn & practice AWS Hacking: [Training](https://hacktricks-training.com)\n> Support HackTricks\n"

SUMMARY = """# SUMMARY.md

# 🌐 Pentesting Web

- [Pentesting Web](pentesting-web/README.md)
  - [SQL Injection](pentesting-web/sql-injection/README.md)
    - [MySQL Injection](pentesting-web/sql-injection/mysql-injection.md)
- [Network](network-services-pentesting/README.md)

# 🗑️ TODO

- [Draft](todo/draft.md)
"""

WEB_README = """# Pentest Web

{{#include ../../banners/hacktricks-training.md}}

## Visão geral

Veja [Injeção de SQL](sql-injection/README.md) e um [site externo](https://owasp.org).

![captura de tela](<../images/image (1).png>)
"""

SQL_README = """# Injeção de SQL

{{#include ../../banners/hacktricks-training.md}}

> [!TIP]
> Linha de resumo real para SQLi.

## Union based

```sql
-1 UNION SELECT username, password FROM users--
```
"""

MYSQL = """# MySQL Injection

{{#include ../../../banners/hacktricks-training.md}}

## Extract

```sql
SELECT @@version;
```
"""

NETWORK = """# Network

{{#include ../../banners/hacktricks-training.md}}

## Services

{{#include ../banners/hacktricks-training.md}}
"""


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "hacktricks"
    src = root / "src"
    files = {
        "SUMMARY.md": SUMMARY,
        "pentesting-web/README.md": WEB_README,
        "pentesting-web/sql-injection/README.md": SQL_README,
        "pentesting-web/sql-injection/mysql-injection.md": MYSQL,
        "network-services-pentesting/README.md": NETWORK,
        "todo/draft.md": "# Draft\n\nnothing\n",
        "banners/hacktricks-training.md": BANNER,
        "LICENSE.md": "CC BY-NC 4.0 - Copyright © Carlos Polop\n",
    }
    for rel, text in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    img = src / "images" / "image (1).png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"],
        cwd=root, check=True,
    )
    # The wiki keeps the Brazilian-Portuguese edition on the `pt` branch; the
    # importer detects the language from the checked-out branch.
    subprocess.run(["git", "branch", "-M", "pt"], cwd=root, check=True)
    return root


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return _make_repo(tmp_path_factory.mktemp("ht"))


@pytest.fixture(scope="module")
def images_root(tmp_path_factory):
    return tmp_path_factory.mktemp("ht-images")


@pytest.fixture(scope="module")
def imported(repo, images_root):
    init_db()
    with SessionLocal() as db:
        stats = import_hacktricks(db, repo, images_root=images_root)
        seed_all(db)
        db.commit()
    return stats


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_summary_is_parsed_into_sections(repo):
    sections, nodes = parse_summary(repo / "src")
    assert ("pentesting-web", "Pentesting Web") in sections
    paths = {node.path for node in nodes}
    assert "pentesting-web/sql-injection/README.md" in paths
    assert "todo/draft.md" in paths  # parsed, but skipped at import time


def test_license_is_registered_as_noncommercial_not_redistributable(imported):
    with SessionLocal() as db:
        source = db.query(KB_Source).filter(KB_Source.slug == "hacktricks").one()
        assert source.redistributable is False
        assert source.noncommercial_reuse is True
        assert "BY-NC" in source.license_name
        assert "Carlos Polop" in source.author


def test_imports_content_and_skips_todo_section(imported, repo):
    with SessionLocal() as db:
        docs = db.query(KB_Document).filter(KB_Document.origin == "imported").all()
        paths = {doc.source_path for doc in docs}
        # SUMMARY.md, the licence file, the banner partial and todo/ are not pages.
        assert "SUMMARY.md" not in paths
        assert "LICENSE.md" not in paths
        assert "todo/draft.md" not in paths
        assert "pentesting-web/sql-injection/README.md" in paths
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        for doc in docs:
            assert doc.source_commit == sha
            assert sha in doc.source_url
            # The `pt` branch is Brazilian Portuguese: detected as pt-BR and
            # marked translated, not left as untranslated English.
            assert doc.language == "pt-BR"
            assert doc.translation_status == "translated"


_PT_TOKENS = re.compile(
    r"(?<![\w-])("
    r"[a-zà-ÿ]+(?:ção|ções|mente|dade|agem|ável|ível|ória|ório|ância|ência|eiro|eiros)"
    r"|que|não|para|com|uma|dos|das|pelo|pela|está|são|também|quando|onde|como|isso|"
    r"este|esta|esse|essa|sobre|entre|através|após|durante|pode|podem|deve|devem|será|"
    r"fazer|usar|usando|verificar|executar|obter"
    r")(?![\w-])",
    re.I,
)
_EN_TOKENS = re.compile(
    r"(?<![\w-])(the|this|that|these|those|and|with|without|which|you|your|can|cannot|"
    r"should|must|will|would|from|there|they|their|when|where|how|is|are|was|were|be|"
    r"been|being|it|its|as|at|on|in|by|has|have|had|may|might|need|use|using|used|"
    r"page|file|code)(?![\w-])",
    re.I,
)


def _looks_english(body: str) -> bool:
    """True when a page's prose is English, measured against both editions.

    Three attempts were needed, each rejected by measuring on the two real
    branches instead of trusting the pattern:

    1. "no Portuguese function word" — English technical prose keeps a few
       ``a``/``o``/``e`` one-letter tokens (code, list markers), so it never
       reached zero: the English edition passed;
    2. "more English than Portuguese function words" — pt-BR pages quote long
       English output (exploit logs, HTTP dumps), so 13% of the pt-BR library
       was flagged and the signal drowned;
    3. heading-only comparison — pt-BR headings often carry unaccented words
       ("Informacoes Básicas"), which an accented token list misses.

    What works is density over the whole body: quoting is local, an English
    *edition* is English everywhere. Measured offline: 0.2% of the pt-BR
    library flagged (the 2 docs that are mostly quoted English), 91.7% of the
    English edition flagged.
    """
    words = len(body.split())
    if words < 40:
        return False
    pt_hits, en_hits = len(_PT_TOKENS.findall(body)), len(_EN_TOKENS.findall(body))
    if pt_hits + en_hits < 20:
        return False
    return en_hits / words > 0.12 and en_hits > 2.5 * pt_hits


def test_pt_branch_import_does_not_ship_english_prose(imported):
    """Guards against importing the English edition by mistake.

    ``git clone --branch pt`` is the whole point of the HackTricks import: the
    pt-BR edition is what the library promises. If someone clones ``master``
    (the default branch — easy to do by accident) the other assertions here
    still pass: commit, attribution, paths, and even ``language`` (the source
    row declares ``branch: pt`` by default, so detection labels English text
    as pt-BR/translated). Only measuring the text catches it.
    """
    with SessionLocal() as db:
        docs = db.query(KB_Document).filter(KB_Document.origin == "imported").all()
        assert docs, "nada importado: o teste não teria o que medir"
        offenders = [
            doc.source_path
            for doc in docs
            if _looks_english(doc.body_md.split("alterações locais são marcadas abaixo.", 1)[-1])
        ]
    assert len(offenders) <= len(docs) * 0.05, (
        f"biblioteca majoritariamente em inglês ({len(offenders)}/{len(docs)}); "
        f"faça o clone com --branch pt: {offenders[:5]}"
    )


def test_attribution_and_nc_notice_are_prepended_and_banner_removed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    body = build_body(
        SQL_README,
        md_path=src / "pentesting-web/sql-injection/README.md",
        src_root=src,
        images=ImageStore(tmp_path / "img"),
        doc_slug_by_path={},
        sha="a" * 40,
    )
    assert "Créditos" in body and "Carlos Polop" in body
    assert "CC BY-NC 4.0" in body
    assert "não comercial" in body.lower()
    assert "{{#include" not in body
    assert "hacktricks-training" not in body
    # Payload text is preserved verbatim.
    assert "-1 UNION SELECT username, password FROM users--" in body


def test_relative_md_links_become_reader_links_and_images_are_localised(
    imported, images_root
):
    with SessionLocal() as db:
        doc = db.query(KB_Document).filter(
            KB_Document.source_path == "pentesting-web/README.md"
        ).one()
        assert "](/kb/d/ht-pentesting-web-sql-injection)" in doc.body_md
        # External links untouched.
        assert "https://owasp.org" in doc.body_md
        # No dangling relative markdown links remain.
        assert "](sql-injection/README.md)" not in doc.body_md
        # Image rewritten to the served static path, and the file copied to the
        # configured on-disk static root.
        assert "/static/hacktricks/images/image%20%281%29.png" in doc.body_md
        copies = list(Path(images_root).rglob("*.png"))
        assert copies, "referenced image must be copied to the static root"


def test_reimport_is_idempotent_and_keeps_reviewed_bodies(repo, images_root):
    with SessionLocal() as db:
        before = db.query(KB_Document).count()
        doc = db.query(KB_Document).filter(
            KB_Document.source_path == "pentesting-web/sql-injection/mysql-injection.md"
        ).one()
        doc.translation_status = "reviewed"
        doc.body_md = "# Tradução revisada à mão"
        db.commit()

        stats = import_hacktricks(db, repo, images_root=images_root)
        db.commit()
        assert db.query(KB_Document).count() == before
        assert stats["created"] == 0
        assert doc.body_md == "# Tradução revisada à mão"


def test_reader_page_shows_attribution_and_nc_notice(client):
    page = client.get("/kb/d/ht-pentesting-web-sql-injection")
    assert page.status_code == 200
    assert "Origem do conteúdo" in page.text
    assert "Uso não comercial" in page.text
    assert "Carlos Polop" in page.text
    assert "CC BY-NC 4.0" in page.text


def test_sources_page_distinguishes_nc_license(client):
    page = client.get("/kb/sources")
    assert page.status_code == 200
    assert "Parcial — uso não comercial com atribuição" in page.text

# ---------------------------------------------------------------------------
# Own documents (content/kb_own) — written for REDVAULT, searchable like the rest
# ---------------------------------------------------------------------------

def test_own_documents_are_indexed_and_found_by_search(client):
    """The 24 pt-BR docs authored for the Learning Paths must be reachable.

    Seeding registers them with ``origin='own'``; the FTS5 index must return
    each one for its own title, otherwise the curriculum theory links lead to
    content the operator cannot find.
    """
    from app.kb_own import load_own_documents
    from app.kb_search import rebuild, search

    with SessionLocal() as db:
        own = db.query(KB_Document).filter(KB_Document.origin == "own").all()
        local = load_own_documents()
        assert len(own) == len(local) >= 24
        assert all(doc.language == "pt-BR" for doc in own)
    rebuild()
    for doc in own:
        hits = search(doc.title, limit=20)
        assert doc.slug in {hit["slug"] for hit in hits}, doc.slug


def test_own_documents_are_searchable_from_the_library_page(client):
    response = client.get("/kb", params={"q": "cadeia de custódia"})
    assert response.status_code == 200
    assert "own-forense-cadeia-custodia" in response.text
