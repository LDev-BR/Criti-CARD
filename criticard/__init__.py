"""Flask application factory and module registration."""
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import ROOT, defaults, ensure_secret_key, validate_runtime


def create_app(config=None):
    app = Flask(__name__, template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"), instance_path=str(ROOT / "instance"))
    app.config.from_mapping(defaults())
    app.config.update(config or {})
    if config and "DATABASE" in config and "DATABASE_URL" not in config:
        app.config["DATABASE_URL"] = None
    validate_runtime(app)
    for key in ("DATABASE", "UPLOAD_FOLDER", "CAPA_FOLDER"):
        path = Path(app.config[key]).expanduser()
        app.config[key] = str(path if path.is_absolute() else ROOT / path)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    ensure_secret_key(app)
    for key in ("UPLOAD_FOLDER", "CAPA_FOLDER"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    from . import accounts, admin, admin_catalog, auth, backlog, cards, chat, community, communities, db, discovery, profiles, security, form_security, presentation, storage, transfer, settings, privacy
    from .accounts import settings as account_settings
    from .social import views as social
    from .social import people_views as people
    db.init_app(app)
    from .communities import views as communities_views
    transfer.init_app(app)
    from .progression.cli import register_cli
    register_cli(app)
    from . import progression
    app.register_blueprint(progression.bp)
    from .progression import presentation as progression_presentation
    progression_presentation.init_app(app)
    from .progression import admin_views as progression_admin
    app.register_blueprint(progression_admin.bp)
    storage.init_app(app)
    security.init_app(app)
    form_security.init_app(app)
    presentation.init_app(app)
    for module in (auth, profiles, cards, admin, admin_catalog, community, communities_views, discovery, backlog, social, people, chat, accounts, settings, account_settings, privacy):
        app.register_blueprint(module.bp)
    privacy.init_app(app)
    chat.init_app(app)
    if app.config['PROXY_HOPS']:
        # Proxy headers must reach Socket.IO as well as Flask's HTTP routes.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config['PROXY_HOPS'], x_proto=app.config['PROXY_HOPS'])
    @app.get('/media/<kind>/<filename>')
    def public_image(kind, filename):
        if kind not in storage.KINDS or not storage.valid_image_name(filename):
            abort(404)
        folder_key = storage.KINDS[kind][0]
        return send_from_directory(app.config[folder_key], filename, max_age=86400)

    if app.testing:
        with app.app_context():
            db.init_db()
            db.ensure_admin()

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    @app.errorhandler(401)
    @app.errorhandler(422)
    @app.errorhandler(429)
    def request_error(error):
        messages = {
            400: "O formulário expirou ou é inválido. Volte e tente novamente.",
            403: "Você não tem permissão para realizar esta ação.",
            404: "Não encontramos esta página ou publicação.",
            405: "Esta ação precisa ser enviada pelo formulário da página.",
            413: "O envio excedeu 3 MB. Escolha uma imagem menor.",
            401: "Faça login para continuar.",
            422: "Confira os dados enviados.",
            429: "Muitas tentativas. Aguarde um momento.",
        }
        if security.wants_json():
            return jsonify(error=error.description if error.code in (422,429) else messages[error.code]), error.code
        return render_template("error.html", code=error.code, message=messages[error.code]), error.code
    return app
