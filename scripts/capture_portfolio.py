"""Capture real Criti-CARD pages using disposable, wholly fictional data.

Run from any directory with the project's Python environment. This script never
imports app.py, reads .env, or connects to the configured application database.
Playwright is optional tooling: it is not an application dependency.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Thread
from urllib.parse import urlsplit
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Portfolio1!"
DESKTOP = {"width": 1440, "height": 960}
MOBILE = {"width": 390, "height": 844}
FILENAMES = (
    "discovery-desktop.png", "reviews-desktop.png", "catalog-desktop.png",
    "community-desktop.png", "chat-desktop.png", "journey-mobile.png",
)


@contextmanager
def isolated_environment():
    """Prevent dotenv and inherited service credentials from affecting defaults."""
    replacements = {
        "PYTHON_DOTENV_DISABLED": "1", "ENVIRONMENT": "development",
        "HOST": "127.0.0.1", "PORT": "5000", "PROXY_HOPS": "0",
        "FLASK_DEBUG": "0", "SESSION_COOKIE_SECURE": "0",
        "STORAGE_BACKEND": "local", "ACCOUNT_MAIL_BACKEND": "disabled",
        "ACCOUNT_SMTP_PORT": "587", "ACCOUNT_SMTP_TLS": "starttls",
    }
    for name in (
        "SECRET_KEY", "DATABASE", "DATABASE_URL", "UPLOAD_FOLDER", "CAPA_FOLDER",
        "TRUSTED_HOSTS", "ADM_USERNAME", "ADM_SENHA", "ADM_EMAIL",
        "S3_ENDPOINT_URL", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY", "S3_PUBLIC_BASE_URL", "S3_PREFIX",
        "ACCOUNT_BASE_URL", "ACCOUNT_OUTBOX_PATH", "ACCOUNT_MAIL_FROM",
        "ACCOUNT_SMTP_HOST", "ACCOUNT_SMTP_USERNAME", "ACCOUNT_SMTP_PASSWORD",
        "PRIVACY_CONTROLLER_NAME", "PRIVACY_CONTACT_EMAIL",
    ):
        replacements[name] = ""
    original = {name: os.environ.get(name) for name in replacements}
    os.environ.update(replacements)
    try:
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def output_directory(value: str) -> Path:
    """Only write the public artifacts into a dedicated repository directory."""
    output = Path(value).expanduser()
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output == ROOT:
        raise ValueError("--output must be a dedicated directory within this repository")
    forbidden = {".git", ".agents", ".codex", ".aws", ".runtime", "instance", "static"}
    if forbidden.intersection(output.relative_to(ROOT).parts):
        raise ValueError("--output cannot target source assets, private data or internal directories")
    for filename in (*FILENAMES, "manifest.json"):
        destination = output / filename
        if destination.is_symlink() or destination.is_dir():
            raise ValueError(f"Refusing to overwrite a link or directory: {destination}")
    return output


def make_application(temporary: Path):
    from criticard import create_app
    from criticard.db import init_db

    config = {
        "TESTING": False, "ENVIRONMENT": "development", "DEBUG": False,
        "SECRET_KEY": "fictional-portfolio-only-not-a-deployment-secret",
        "DATABASE": str(temporary / "portfolio.sqlite"), "DATABASE_URL": None,
        "UPLOAD_FOLDER": str(temporary / "avatars"),
        "CAPA_FOLDER": str(temporary / "covers"),
        "ADM_USERNAME": "", "ADM_SENHA": "", "ADM_EMAIL": "",
        "STORAGE_BACKEND": "local", "ACCOUNT_MAIL_BACKEND": "disabled",
        "ACCOUNT_BASE_URL": "", "ACCOUNT_OUTBOX_PATH": str(temporary / "outbox"),
        "ACCOUNT_MAIL_FROM": "", "ACCOUNT_SMTP_HOST": "",
        "ACCOUNT_SMTP_USERNAME": "", "ACCOUNT_SMTP_PASSWORD": "",
        "S3_ENDPOINT_URL": "", "S3_BUCKET": "", "S3_ACCESS_KEY_ID": "",
        "S3_SECRET_ACCESS_KEY": "", "S3_PUBLIC_BASE_URL": "", "S3_PREFIX": "",
        "PRIVACY_CONTROLLER_NAME": "Demonstração fictícia",
        "PRIVACY_CONTACT_EMAIL": "", "SESSION_COOKIE_SECURE": False,
        "PROXY_HOPS": 0, "TRUSTED_HOSTS": ["127.0.0.1"],
    }
    application = create_app(config)
    try:
        application.instance_path = str(temporary / "instance")
        assets = temporary / "static"
        # User uploads never enter the server's static tree.
        shutil.copytree(ROOT / "static", assets,
                        ignore=shutil.ignore_patterns("uploads", "cards"))
        application.static_folder = str(assets)
        with application.app_context():
            init_db()
        return application
    except BaseException:
        application.extensions["database_engine"].dispose()
        raise


def seed_fictional_data(application, now: datetime) -> int:
    from sqlalchemy import insert, select
    from werkzeug.security import generate_password_hash
    from criticard.backlog.models import BacklogItem
    from criticard.catalog_images import art_for_work
    from criticard.chat.models import Conversation, ConversationMember, Message
    from criticard.communities.models import (
        Community, CommunityComment, CommunityMembership, CommunityPost, CommunityReaction,
    )
    from criticard.db import get_db
    from criticard.models import Card, Category, User, Work
    from criticard.progression.service import record_action, sync_user
    from criticard.social.models import CardLike, CategoryFollow, Comment, Follow, Friend, WorkFollow

    personas = (
        ("NARA", "Nara", "Entre livros, filmes e mundos imaginários."),
        ("LEO", "Leo", "Histórias que continuam depois dos créditos."),
        ("MAYA", "Maya", "Uma boa descoberta sempre merece conversa."),
        ("TOM", "Tom", "Jogos, cinema e uma lista que só cresce."),
    )
    with application.app_context(), get_db() as db:
        for identifier, (username, name, bio) in enumerate(personas, 1):
            db.execute(insert(User).values(
                id=identifier, username=username, nome=name, apelido="Leitor",
                about=bio, email=f"{username.lower()}@example.invalid",
                senha=generate_password_hash(PASSWORD), admin=0, active=1,
                search_name=name.casefold(), created_at=now - timedelta(days=95),
            ))
        works = {row["id"]: row for row in db.execute(select(
            Work.__table__, Category.slug.label("category_slug")
        ).join(Category, Work.categoria_id == Category.id)).fetchall()}

        def review(author, work_id, score, body, when):
            work = works[work_id]
            illustration = art_for_work(work)
            card_id = db.execute(insert(Card).values(
                author_id=author, obra_id=work_id, titulo=work["titulo"],
                capa=illustration["marker"] if illustration else "default-cover.svg",
                nota=score, sobre=body, search_title=work["titulo"].casefold(),
                archived=0, created_at=when, updated_at=when,
            ).returning(Card.id)).scalar()
            record_action(db, author, "card_published", when,
                          work_id=work_id, category_id=work["categoria_id"])
            return card_id

        # Real ledger operations on three different fictional contribution days.
        # No direct XP edits, production gate overrides or invented real history.
        for work_id in range(1, 16):
            when = now - timedelta(days=14 - (work_id - 1) // 5, hours=work_id % 5)
            review(1, work_id, 82 + work_id % 14,
                   "Uma descoberta que vale revisitar. O cuidado com o ritmo e os "
                   "personagens transforma pequenos detalhes em momentos memoráveis.", when)

        recent = (
            (2, 2, 96, "Um reino silencioso que conta sua história nos detalhes. "
             "Explorar sem pressa faz cada encontro parecer uma descoberta.", 22),
            (3, 6, 94, "A imensidão do espaço encontra uma história muito humana. "
             "A trilha e as escolhas visuais tornam a experiência inesquecível.", 20),
            (2, 17, 91, "Política, ecologia e imaginação em um universo que pede atenção. "
             "A leitura cresce quando as peças começam a se conectar.", 18),
            (4, 4, 93, "Cada tentativa traz uma conversa, um detalhe e uma nova vontade "
             "de continuar. Mecânicas e narrativa caminham juntas.", 16),
            (3, 12, 90, "Um quebra-cabeça que recompensa olhar com cuidado. A atmosfera "
             "e as relações entre os personagens sustentam a curiosidade.", 14),
            (2, 8, 92, "Ideias que continuam provocando perguntas depois do filme. "
             "O visual e as cenas de ação servem a uma história cheia de possibilidades.", 12),
            (1, 16, 89, "Uma leitura inquietante sobre linguagem, memória e poder. "
             "Ainda rende ótimas conversas sobre o mundo que construímos.", 10),
            (1, 26, 95, "Arte intensa e personagens cheios de camadas. Há muito a "
             "observar na maneira como cada página organiza a emoção.", 8),
        )
        for author, work_id, score, body, hours in recent:
            card_id = review(author, work_id, score, body, now - timedelta(hours=hours))
            for fan in (1, 2, 3, 4):
                if fan != author:
                    db.execute(insert(CardLike).values(user_id=fan, card_id=card_id,
                                                       created_at=now - timedelta(hours=2)))
            commenter = 3 if author != 3 else 2
            db.execute(insert(Comment).values(
                author_id=commenter, card_id=card_id,
                body="Também fiquei pensando nesses detalhes. Ótima descoberta!",
                created_at=now - timedelta(hours=1), updated_at=now - timedelta(hours=1)))

        for work_id, status in ((2, "completed"), (6, "completed"), (16, "completed"),
                                (17, "in_progress"), (26, "planned")):
            db.execute(insert(BacklogItem).values(
                user_id=1, work_id=work_id, status=status, visibility="private",
                created_at=now - timedelta(days=5), updated_at=now - timedelta(days=2)))
            if status == "completed":
                record_action(db, 1, "work_completed", now - timedelta(days=2),
                              work_id=work_id, category_id=works[work_id]["categoria_id"])
        db.execute(insert(Friend).values(user_low_id=1, user_high_id=2,
            requested_by=1, status="accepted", created_at=now - timedelta(days=8),
            updated_at=now - timedelta(days=7), accepted_at=now - timedelta(days=7)))
        db.execute(insert(Follow).values(user_id=1, target_id=2, created_at=now))
        db.execute(insert(CategoryFollow).values(user_id=1, category_id=2, created_at=now))
        db.execute(insert(WorkFollow).values(user_id=1, work_id=17, created_at=now))

        community_id = db.execute(insert(Community).values(
            slug="entre-paginas-e-telas", name="Entre páginas e telas",
            description="Um espaço para descobrir histórias, trocar interpretações "
                        "e conversar sobre o que fica depois da última página.",
            theme="gold", icon="book", mode="open", minimum_level=1,
            created_by=2, seeded=0, archived=0,
            created_at=now - timedelta(days=10), updated_at=now,
        ).returning(Community.id)).scalar()
        for user_id in (2, 3, 4):
            db.execute(insert(CommunityMembership).values(
                community_id=community_id, user_id=user_id,
                role="owner" if user_id == 2 else "member", joined_at=now - timedelta(days=7)))
        for author, work_id, title, body, hours in (
            (2, 17, "Qual adaptação abriu as portas para um livro?",
             "Comecei Duna depois do filme e encontrei outro ritmo para a mesma história. "
             "Que adaptação fez vocês procurarem a obra original?", 3),
            (3, 6, "Quando a trilha também conta a história",
             "Revisitei Interestelar e percebi como a música muda a sensação do tempo. "
             "Qual cena vocês lembram primeiro quando ouvem a trilha?", 6),
        ):
            post_id = db.execute(insert(CommunityPost).values(
                community_id=community_id, author_id=author, work_id=work_id,
                title=title, body=body, created_at=now - timedelta(hours=hours),
                updated_at=now - timedelta(hours=hours),
            ).returning(CommunityPost.id)).scalar()
            db.execute(insert(CommunityComment).values(post_id=post_id, author_id=4,
                body="Gosto de perceber o que muda entre essas formas de contar.",
                created_at=now - timedelta(hours=1), updated_at=now - timedelta(hours=1)))
            db.execute(insert(CommunityReaction).values(post_id=post_id, user_id=4,
                kind="insightful", created_at=now - timedelta(hours=1)))

        conversation_id = db.execute(insert(Conversation).values(
            pair_low_id=1, pair_high_id=2, kind="direct", created_at=now - timedelta(days=1),
        ).returning(Conversation.id)).scalar()
        for user_id in (1, 2):
            db.execute(insert(ConversationMember).values(
                conversation_id=conversation_id, user_id=user_id, role="member",
                joined_at=now - timedelta(days=1)))
        messages = (
            (2, "Vi sua crítica de 1984. Gostei da leitura sobre memória e linguagem."),
            (1, "Obrigada! É daqueles livros que continuam rendendo perguntas."),
            (2, "Estou lendo Duna agora. A construção do mundo é impressionante."),
            (1, "Está na minha coleção também. Depois podemos conversar na comunidade!"),
        )
        for index, (author, body) in enumerate(messages, 1):
            db.execute(insert(Message).values(conversation_id=conversation_id,
                sender_id=author, body=body, client_nonce=str(UUID(int=index)),
                created_at=now - timedelta(minutes=30 - index * 4)))
        for user_id in range(1, 5):
            sync_user(db, user_id, now)
    return conversation_id


def sign_in(page, origin: str):
    page.goto(origin + "/", wait_until="networkidle")
    page.locator("#username").fill("NARA")
    page.locator("#senha").fill(PASSWORD)
    page.locator("button[type=submit]").first.click()
    page.wait_for_url(origin + "/dashboard")


def capture_pages(application, temporary: Path, channel: str | None, now: datetime):
    from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright
    from werkzeug.serving import make_server

    conversation_id = seed_fictional_data(application, now)
    server = make_server("127.0.0.1", 0, application, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    browser = None
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    artifacts = temporary / "captures"
    artifacts.mkdir()
    errors, failed_responses, external_requests = [], [], []
    metadata = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel, headless=True)
            desktop = browser.new_context(viewport=DESKTOP, device_scale_factor=1,
                locale="pt-BR", timezone_id="UTC", color_scheme="light", reduced_motion="reduce")

            def observe(context):
                def local_only(route):
                    if route.request.url.startswith(origin + "/"):
                        route.continue_()
                    else:
                        external_requests.append(route.request.url)
                        route.abort()
                context.route("**/*", local_only)
                context.on("page", lambda page: (
                    page.on("pageerror", lambda error: errors.append(str(error))),
                    page.on("console", lambda message: errors.append(message.text)
                            if message.type == "error" else None),
                    page.on("response", lambda response: failed_responses.append(
                        {"path": urlsplit(response.url).path, "status": response.status})
                        if response.status >= 400 else None),
                ))

            observe(desktop)
            page = desktop.new_page()
            sign_in(page, origin)

            def capture(page, route, filename, title, content, viewport):
                response = page.goto(origin + route, wait_until="networkidle")
                assert response and response.status == 200, f"Page failed: {route}"
                assert title in page.title(), f"Wrong page title: {route}"
                expect(page.get_by_role("heading", name=content, exact=True)).to_be_visible()
                page.evaluate("document.fonts.ready")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), \
                    f"Horizontal overflow: {route}"
                page.mouse.move(0, 0)
                page.screenshot(path=str(artifacts / filename), full_page=False, animations="disabled")
                metadata.append({"filename": filename, "route": route, "title": page.title(),
                                 "viewport": viewport, "full_page": False})
                print(f"Captured {filename} ({viewport['width']} x {viewport['height']})")

            capture(page, "/feed", FILENAMES[0], "Descobrir", "Boas-vindas, Nara.", DESKTOP)
            capture(page, "/criticas", FILENAMES[1], "Feed de críticas",
                    "Críticas que abrem novas perspectivas.", DESKTOP)
            capture(page, "/catalogo", FILENAMES[2], "Catálogo", "Um mundo para descobrir.", DESKTOP)
            # Exercise the actual live-search control and verify its rendered result.
            page.locator("#backlog-q").fill("Hades")
            expect(page.locator(".catalog-work")).to_have_count(1)
            expect(page.locator(".catalog-work h3")).to_have_text("Hades")
            capture(page, "/comunidades/entre-paginas-e-telas", FILENAMES[3],
                    "Entre páginas e telas", "Entre páginas e telas", DESKTOP)
            capture(page, f"/mensagens/{conversation_id}", FILENAMES[4], "Conversa com Leo",
                    "Mensagens", DESKTOP)
            expect(page.locator("[data-chat-status]")).to_have_text("Conectado")
            page.locator("#chat-body").fill("Combinado! Uma boa história sempre rende conversa.")
            page.get_by_role("button", name="Enviar", exact=True).click()
            expect(page.locator(".chat-bubble p").last).to_have_text(
                "Combinado! Uma boa história sempre rende conversa.")
            # Capture after the genuine CSRF-protected realtime send completed.
            page.mouse.move(0, 0)
            page.screenshot(path=str(artifacts / FILENAMES[4]), full_page=False, animations="disabled")
            mobile = browser.new_context(viewport=MOBILE, device_scale_factor=1,
                locale="pt-BR", timezone_id="UTC", color_scheme="light", reduced_motion="reduce",
                storage_state=desktop.storage_state())
            observe(mobile)
            mobile_page = mobile.new_page()
            capture(mobile_page, "/jornada", FILENAMES[5], "Minha jornada", "Minha jornada", MOBILE)
            assert not errors, f"Browser errors: {errors}"
            assert not failed_responses, f"Failed HTTP responses: {failed_responses}"
            assert not external_requests, f"Unexpected external requests: {external_requests}"
            version = browser.version
            mobile.close()
            desktop.close()
            browser.close()
            browser = None
        for item in metadata:
            image = artifacts / item["filename"]
            item.update(bytes=image.stat().st_size, sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        return artifacts, {
            "generated_at_utc": now.isoformat(), "data": "wholly fictional",
            "browser": "Chromium", "channel": channel or "chromium", "browser_version": version,
            "browser_plugin": "not available; local Playwright used",
            "checks": {"http": "passed", "page_identity": "passed", "content": "passed",
                       "console_errors": [], "horizontal_overflow": False, "external_requests": [],
                       "interactions": ["form login with CSRF", "catalog live search", "realtime chat send"]},
            "screenshots": metadata,
        }
    finally:
        try:
            if browser is not None:
                try:
                    browser.close()
                except PlaywrightError:
                    # sync_playwright already closes its processes when an earlier
                    # validation failed; preserve that original error.
                    pass
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/screenshots", help="Dedicated directory within the repository")
    parser.add_argument("--channel", default=os.getenv("PLAYWRIGHT_CHANNEL") or ("msedge" if os.name == "nt" else None),
                        help="Playwright Chromium channel (default: Edge on Windows, Chromium elsewhere)")
    arguments = parser.parse_args()
    output = output_directory(arguments.output)
    sys.path.insert(0, str(ROOT))
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with isolated_environment(), tempfile.TemporaryDirectory(prefix="criticard-portfolio-") as temporary_name:
        temporary = Path(temporary_name)
        application = make_application(temporary)
        try:
            artifacts, metadata = capture_pages(application, temporary, arguments.channel, now)
            output.mkdir(parents=True, exist_ok=True)
            # Publish only successful captures. Never remove the destination directory.
            for filename in FILENAMES:
                shutil.copyfile(artifacts / filename, output / filename)
            (output / "manifest.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            application.extensions["database_engine"].dispose()
    print(f"Six real screenshots saved in {output.relative_to(ROOT).as_posix()}; all checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
