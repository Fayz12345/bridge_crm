import logging
from typing import Any

from markupsafe import Markup, escape
from flask import Flask, g, has_request_context, jsonify, redirect, request, session, url_for
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from bridge_crm.config import Settings, get_settings
from bridge_crm.api.lead_capture import lead_capture_bp
from bridge_crm.crm.accounts.routes import accounts_bp
from bridge_crm.crm.auth.queries import get_user_by_id
from bridge_crm.crm.auth.routes import auth_bp
from bridge_crm.crm.custom_fields.routes import custom_fields_bp
from bridge_crm.crm.dashboard.routes import dashboard_bp
from bridge_crm.crm.leads.routes import leads_bp
from bridge_crm.crm.marketing.routes import marketing_bp
from bridge_crm.crm.notifications.queries import count_unread_notifications
from bridge_crm.crm.notifications.routes import notifications_bp
from bridge_crm.crm.opportunities.routes import opportunities_bp
from bridge_crm.crm.products.routes import products_bp
from bridge_crm.crm.reports.routes import reports_bp
from bridge_crm.crm.setup.routes import setup_bp
from bridge_crm.crm.users.routes import users_bp
from bridge_crm.db.bootstrap import initialize_database
from bridge_crm.db.engine import get_engine

csrf = CSRFProtect()


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(settings.to_flask_config())
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_prefix=1)

    _configure_logging(app)
    csrf.init_app(app)

    @app.template_filter("nl2br")
    def nl2br_filter(value):
        if not value:
            return ""
        return Markup(escape(value).replace("\n", Markup("<br>")))

    try:
        initialize_database()
    except Exception:
        app.logger.exception("Database bootstrap check failed")

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(marketing_bp)
    app.register_blueprint(opportunities_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(custom_fields_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(lead_capture_bp)
    csrf.exempt(lead_capture_bp)

    @app.before_request
    def load_current_user() -> None:
        user_id = session.get("user_id")
        g.user = get_user_by_id(user_id) if user_id else None

    @app.route("/")
    def index() -> Any:
        if session.get("user_id"):
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    @app.route("/health")
    def health() -> Any:
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "db": "ok"})
        except Exception:
            app.logger.exception("Health check failed")
            return jsonify({"status": "error", "db": "error"}), 503

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if request.endpoint == "lead_capture.lead_form":
            allowed_parents = app.config.get("LEAD_FORM_ALLOWED_PARENTS", [])
            if allowed_parents:
                response.headers["Content-Security-Policy"] = (
                    "frame-ancestors " + " ".join(allowed_parents)
                )
            response.headers.pop("X-Frame-Options", None)
        else:
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "app_settings": settings,
            "current_endpoint": request.endpoint if has_request_context() and request.endpoint else "",
            "unread_notifications_count": count_unread_notifications(g.user["id"]) if g.get("user") else 0,
        }

    return app


def _configure_logging(app: Flask) -> None:
    if app.logger.handlers:
        return

    level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    app.logger.setLevel(level)
    app.logger.addHandler(handler)
