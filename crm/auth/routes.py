import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func, insert, select
from werkzeug.security import check_password_hash, generate_password_hash

from bridge_crm.crm.auth.queries import (
    clear_login_attempts,
    count_recent_failed_attempts,
    create_password_reset_token,
    get_active_password_reset_token,
    get_user_by_email,
    invalidate_password_reset_tokens,
    mark_password_reset_token_used,
    record_login_attempt,
    set_user_password,
)
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_rate_limits
from bridge_crm.integrations.email_sender import send_email, smtp_configured

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
    template_folder="../../templates",
)

PASSWORD_RESET_TOKEN_HOURS = 2
PASSWORD_RESET_LIMIT_COUNT = 5
PASSWORD_RESET_LIMIT_WINDOW_SECONDS = 3600


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*roles):
    allowed_roles = {role.strip().lower() for role in roles if role}

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            user_role = (g.user or {}).get("role")
            if user_role not in allowed_roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard.index"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def admin_required(view):
    return roles_required("admin")(view)


def _client_ip() -> str:
    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    return ip_address.split(",")[0].strip()


def _too_many_reset_requests(ip_address: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PASSWORD_RESET_LIMIT_WINDOW_SECONDS)
    statement = select(func.count()).select_from(crm_rate_limits).where(
        crm_rate_limits.c.ip_address == ip_address,
        crm_rate_limits.c.endpoint == "/auth/forgot-password",
        crm_rate_limits.c.created_at >= cutoff,
    )
    with get_connection() as connection:
        count = connection.execute(statement).scalar_one()
    return int(count) >= PASSWORD_RESET_LIMIT_COUNT


def _record_reset_request(ip_address: str) -> None:
    statement = insert(crm_rate_limits).values(
        ip_address=ip_address,
        endpoint="/auth/forgot-password",
    )
    with get_connection() as connection:
        connection.execute(statement)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_password_reset_email(
    user: dict,
    requested_by: int | None = None,
    requested_by_name: str | None = None,
) -> None:
    if not smtp_configured():
        raise RuntimeError("Email delivery is not configured.")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_TOKEN_HOURS)
    invalidate_password_reset_tokens(int(user["id"]))
    create_password_reset_token(
        user_id=int(user["id"]),
        token_hash=_hash_reset_token(token),
        expires_at=expires_at,
        requested_by=requested_by,
    )
    reset_url = url_for("auth.reset_password", token=token, _external=True)

    intro = (
        f"{requested_by_name} sent you a password reset link for Bridge CRM."
        if requested_by_name
        else "A password reset was requested for your Bridge CRM account."
    )
    send_email(
        to_address=user["email"],
        subject="Reset your Bridge CRM password",
        body_text=(
            f"Hi {user['full_name']},\n\n"
            f"{intro}\n\n"
            f"Use the link below to set a new password:\n"
            f"{reset_url}\n\n"
            f"This link expires in {PASSWORD_RESET_TOKEN_HOURS} hours and can only be used once.\n"
            f"If you did not request this change, you can ignore this email."
        ),
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        ip_address = ip_address.split(",")[0].strip()

        if count_recent_failed_attempts(
            ip_address, current_app.config["LOGIN_RATE_LIMIT_WINDOW_SECONDS"]
        ) >= current_app.config["LOGIN_RATE_LIMIT_COUNT"]:
            flash("Too many failed attempts. Try again in 15 minutes.", "danger")
            return render_template("auth/login.html"), 429

        _DUMMY_HASH = generate_password_hash("dummy-constant-time-pad")
        user = get_user_by_email(email) if email else None
        pw_hash = user["password_hash"] if user else _DUMMY_HASH
        password_valid = check_password_hash(pw_hash, password)
        if not user or not password_valid:
            record_login_attempt(email, ip_address, successful=False)
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html"), 401

        if not user["is_active"]:
            flash("Your account is inactive.", "danger")
            return render_template("auth/login.html"), 403

        clear_login_attempts(ip_address, email)
        record_login_attempt(email, ip_address, successful=True)
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["full_name"]
        next_url = request.args.get("next", "")
        if not next_url or urlparse(next_url).netloc:
            next_url = url_for("dashboard.index")
        return redirect(next_url)

    return render_template("auth/login.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if not smtp_configured():
            flash("Password reset email is unavailable right now. Contact an admin.", "warning")
            return render_template("auth/forgot_password.html"), 503

        ip_address = _client_ip()
        if _too_many_reset_requests(ip_address):
            flash("Too many reset requests. Try again in an hour.", "danger")
            return render_template("auth/forgot_password.html"), 429

        email = request.form.get("email", "").strip().lower()
        user = get_user_by_email(email) if email else None
        if user and user.get("is_active"):
            try:
                send_password_reset_email(user)
            except Exception:
                current_app.logger.exception("Password reset email failed")
        _record_reset_request(ip_address)
        flash(
            "If an active account exists for that email, a password reset link has been sent.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    token_record = get_active_password_reset_token(_hash_reset_token(token))
    if not token_record or not token_record.get("is_active"):
        flash("This password reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif password != confirm_password:
            flash("Passwords do not match.", "danger")
        else:
            set_user_password(int(token_record["user_id"]), password)
            mark_password_reset_token_used(int(token_record["id"]))
            session.clear()
            flash("Your password has been reset. You can sign in now.", "success")
            return redirect(url_for("auth.login"))

    return render_template(
        "auth/reset_password.html",
        token=token,
        user_email=token_record["email"],
    )


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
