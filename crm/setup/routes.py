from flask import Blueprint, render_template

from bridge_crm.crm.auth.routes import admin_required

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


@setup_bp.route("/")
@admin_required
def index():
    return render_template("setup/index.html")
