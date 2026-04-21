from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.custom_fields.queries import (
    extract_custom_field_values,
    get_custom_field_values,
    list_custom_fields,
)
from bridge_crm.crm.products.queries import (
    delete_product,
    get_product,
    get_product_filter_options,
    list_products,
    update_product_custom_fields,
)

products_bp = Blueprint(
    "products",
    __name__,
    url_prefix="/products",
    template_folder="../../templates",
)


@products_bp.route("/")
@login_required
def list_view():
    filters = {
        "brand": request.args.get("brand", "").strip() or None,
        "model": request.args.get("model", "").strip() or None,
        "grade": request.args.get("grade", "").strip() or None,
        "status": request.args.get("status", "").strip() or None,
    }
    products = list_products(filters)
    options = get_product_filter_options()
    return render_template(
        "products/list.html",
        products=products,
        filters=filters,
        options=options,
    )


@products_bp.route("/<int:product_id>")
@login_required
def detail_view(product_id: int):
    product = get_product(product_id)
    custom_field_definitions = list_custom_fields("product", active_only=True)
    custom_field_rows = get_custom_field_values(product, custom_field_definitions) if product else []
    return render_template(
        "products/detail.html",
        product=product,
        custom_field_definitions=custom_field_definitions,
        custom_field_rows=custom_field_rows,
    )


@products_bp.route("/<int:product_id>/custom-fields", methods=["POST"])
@login_required
def update_custom_fields_view(product_id: int):
    product = get_product(product_id)
    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("products.list_view"))

    custom_field_definitions = list_custom_fields("product", active_only=True)
    custom_fields = extract_custom_field_values(request.form, custom_field_definitions)
    update_product_custom_fields(product_id, custom_fields)
    flash("Product custom fields updated.", "success")
    return redirect(url_for("products.detail_view", product_id=product_id))


@products_bp.route("/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_view(product_id: int):
    if g.user["role"] != "admin":
        flash("Only admins can delete products.", "danger")
        return redirect(url_for("products.detail_view", product_id=product_id))

    product = get_product(product_id)
    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("products.list_view"))

    label = f"{product['brand_name']} {product['model_name']}"
    delete_product(product_id)
    flash(f'Product "{label}" deleted.', "success")
    return redirect(url_for("products.list_view"))
