from flask import Blueprint, render_template

from bridge_crm.crm.auth.routes import login_required

marketing_bp = Blueprint(
    "marketing",
    __name__,
    url_prefix="/marketing",
    template_folder="../../templates",
)


@marketing_bp.route("/")
@login_required
def index():
    return render_template("marketing/index.html")
