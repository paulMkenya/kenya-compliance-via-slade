import frappe
from erpnext.controllers.taxes_and_totals import get_itemised_tax_breakup_data
from frappe.model.document import Document

from ...apis.api_builder import EndpointsBuilder
from ...apis.process_request import process_request
from ...apis.remote_response_status_handlers import (
    purchase_invoice_submission_on_success,
)
from ...utils import calculate_tax, get_settings, get_taxation_types

endpoints_builder = EndpointsBuilder()


def validate(doc: Document, method: str = None) -> None:
    get_itemised_tax_breakup_data(doc)
    if not doc.taxes:
        vat_acct = frappe.get_value(
            "Account",
            {"account_type": "Tax", "etims_tax_rate": "16", "company": doc.company},
            ["name"],
            as_dict=True,
        )

        if not vat_acct:
            frappe.throw(
                frappe._(
                    "No 16% VAT Tax Account found for company {0}. "
                    "Please ensure a Tax account with account type 'Tax' "
                    "and tax rate 16 exists."
                ).format(doc.company)
            )

        doc.set(
            "taxes",
            [
                {
                    "account_head": vat_acct.name,
                    "included_in_print_rate": 1,
                    "description": vat_acct.name.split("-", 1)[0].strip(),
                    "category": "Total",
                    "add_deduct_tax": "Add",
                    "charge_type": "On Net Total",
                }
            ],
        )


def on_submit(doc: Document, method: str = None) -> None:
    submit_purchase_invoice(doc)


def submit_purchase_invoice(doc: Document) -> None:
    if doc.is_return == 0:
        # TODO: Handle cases when item tax templates have not been picked
        company_name = (
            doc.company
            # or frappe.defaults.get_user_default("Company")
            # or frappe.get_value("Company", {}, "name")
        )
        settings_doc = get_settings(company_name=company_name)
        if (
            doc.prevent_etims_submission
            or (hasattr(doc, "etr_invoice_number") and doc.etr_invoice_number)
            or not settings_doc
            or not settings_doc.purchase_auto_submission_enabled
        ):
            # If the submission is prevented or if the invoice number is already set, skip submission
            return

        if settings_doc:
            apply_purchase_item_taxes(doc)
            payload = build_purchase_invoice_payload(doc, company_name)
            process_request(
                payload,
                "TrnsPurchaseSaveReq",
                purchase_invoice_submission_on_success,
                request_method="POST",
                doctype="Purchase Invoice",
                settings_name=settings_doc.name,
            )


@frappe.whitelist()
def send_purchase_details(name: str) -> None:
    doc = frappe.get_doc("Purchase Invoice", name)
    submit_purchase_invoice(doc)


def build_purchase_invoice_payload(doc: Document, company_name: str) -> dict:
    taxation_type = get_taxation_types(doc)
    payload = {
        "document_name": doc.name,
        "company_name": company_name,
        "can_send_to_etims": True,
        "paid_invoice_amount": round(doc.grand_total - doc.outstanding_amount, 2),
        "total_amount": round(doc.grand_total, 2),
        "taxable_rate_A": taxation_type.get("A", {}).get("etims_tax_rate", 0),
        "taxable_rate_B": taxation_type.get("B", {}).get("etims_tax_rate", 0),
        "taxable_rate_C": taxation_type.get("C", {}).get("etims_tax_rate", 0),
        "taxable_rate_D": taxation_type.get("D", {}).get("etims_tax_rate", 0),
        "total_taxable_amount": round(doc.base_total, 2),
        "total_tax_amount": round(doc.total_taxes_and_charges, 2),
        "supplier_name": doc.supplier_name,
    }

    return payload


def apply_purchase_item_taxes(doc: Document) -> None:
    """Purchase counterpart of utils.apply_item_taxes_and_codes (which only
    writes Sales Invoice Item): the purchase payload reads etims_tax_amount /
    etims_base_tax_amount / etims_tax_rate / taxation_type_code off each item,
    so compute them with the same calculate_tax engine, set them on the rows
    and persist them where the Purchase Invoice Item fields exist."""
    tax_map = calculate_tax(doc)
    persist = frappe.get_meta("Purchase Invoice Item").has_field("etims_tax_amount")
    for item in doc.items:
        data = tax_map.get(item.name) or {
            "etims_tax_amount": 0.0, "etims_base_tax_amount": 0.0, "etims_tax_rate": 0.0, "taxation_type_code": None,
        }
        item.etims_tax_amount = data["etims_tax_amount"]
        item.etims_base_tax_amount = data["etims_base_tax_amount"]
        item.etims_tax_rate = data["etims_tax_rate"]
        item.taxation_type_code = data["taxation_type_code"]
        if persist:
            frappe.db.set_value(
                "Purchase Invoice Item",
                item.name,
                {
                    "etims_tax_amount": data["etims_tax_amount"],
                    "etims_base_tax_amount": data["etims_base_tax_amount"],
                    "etims_tax_rate": data["etims_tax_rate"],
                    "taxation_type_code": data["taxation_type_code"],
                },
                update_modified=False,
            )
