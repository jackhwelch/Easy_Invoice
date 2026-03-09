import streamlit as st
from fpdf import FPDF
from datetime import datetime, timedelta
from PIL import Image
import json
import os
import pandas as pd
import io
import zipfile
import matplotlib.pyplot as plt
import base64
import streamlit.components.v1 as components
from streamlit_pdf_viewer import pdf_viewer

st.set_page_config(layout="wide")

# --- File paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DETAILS_FILE = os.path.join(BASE_DIR, "my_details.json")
CLIENTS_FILE = os.path.join(BASE_DIR, "clients.json")
INVOICES_FILE = os.path.join(BASE_DIR, "invoices.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
LOGO_FILE = os.path.join(BASE_DIR, "logo.png")


# --- Default settings ---
def default_settings():
    return {
        "business_details": {
            "name": "",
            "address": "",
            "phone": "",
            "email": "",
            "vat_number": "",
            "account_number": "",
            "sort_code": "",
            "swift": ""
        },
        "invoice_defaults": {
            "currency": "AED",
            "tax_percentage": 0.0,
            "payment_terms_days": 30
        },
        "invoice_numbering": {
            "mode": "simple",   # simple / yearly
            "prefix": "INV",
            "digits": 4,
            "separator": "-"
        },
        "display_options": {
            "show_logo": True,
            "show_address": True,
            "show_phone": True,
            "show_email": True,
            "show_vat_number": True,
            "show_bank_details": True,
            "show_payment_terms": True
        },
        "branding": {
            "invoice_logo_file": "",
            "footer_text": "Thank you for your business!"
        }
    }


# --- Utilities ---
def load_json(file_path, default):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return json.load(f)
    return default


def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def merge_settings(loaded, defaults):
    merged = defaults.copy()
    for key, value in defaults.items():
        if key in loaded:
            if isinstance(value, dict) and isinstance(loaded[key], dict):
                merged[key] = value.copy()
                merged[key].update(loaded[key])
            else:
                merged[key] = loaded[key]
    return merged


def sync_my_details_from_settings():
    bd = st.session_state.settings["business_details"]
    st.session_state.my_details = {
        "Name": bd.get("name", ""),
        "Address": bd.get("address", ""),
        "Account Number": bd.get("account_number", ""),
        "Sort Code": bd.get("sort_code", ""),
        "SWIFT": bd.get("swift", "")
    }


# --- Initial load ---
st.session_state.my_details = load_json(DETAILS_FILE, {})
st.session_state.clients = load_json(CLIENTS_FILE, [])
st.session_state.invoices = load_json(INVOICES_FILE, [])

loaded_settings = load_json(SETTINGS_FILE, {})
settings = merge_settings(loaded_settings, default_settings())

# Backward compatibility: if old my_details exists, use it to seed settings
if st.session_state.my_details:
    settings["business_details"]["name"] = settings["business_details"]["name"] or st.session_state.my_details.get("Name", "")
    settings["business_details"]["address"] = settings["business_details"]["address"] or st.session_state.my_details.get("Address", "")
    settings["business_details"]["account_number"] = settings["business_details"]["account_number"] or st.session_state.my_details.get("Account Number", "")
    settings["business_details"]["sort_code"] = settings["business_details"]["sort_code"] or st.session_state.my_details.get("Sort Code", "")
    settings["business_details"]["swift"] = settings["business_details"]["swift"] or st.session_state.my_details.get("SWIFT", "")

st.session_state.settings = settings
sync_my_details_from_settings()

if "page" not in st.session_state:
    st.session_state.page = "main"
if "client_dialog_idx" not in st.session_state:
    st.session_state.client_dialog_idx = None
if "client_dialog_edit_mode" not in st.session_state:
    st.session_state.client_dialog_edit_mode = False
if "previous_selected_clients" not in st.session_state:
    st.session_state.previous_selected_clients = []
if "edit_invoice_idx" not in st.session_state:
    st.session_state.edit_invoice_idx = None
if "confirm_delete_invoices" not in st.session_state:
    st.session_state.confirm_delete_invoices = False


# --- Common UI helpers ---
def page_header(title, back_label=None, back_page=None, help_text=None):
    left, right = st.columns([6, 2])
    with left:
        st.title(title)
        if help_text:
            st.caption(help_text)
    with right:
        if back_label and back_page:
            st.button(
                back_label,
                use_container_width=True,
                on_click=lambda: st.session_state.update({"page": back_page})
            )
    st.markdown("---")


# --- Auto invoice number ---
def get_next_invoice_number(client=None, invoice_date=None):
    global_numbering = st.session_state.settings.get("invoice_numbering", {})
    mode = global_numbering.get("mode", "simple")
    prefix = global_numbering.get("prefix", "INV").strip() or "INV"
    digits = int(global_numbering.get("digits", 4))
    separator = global_numbering.get("separator", "-")

    if client is not None and client.get("Use Custom Numbering", False):
        mode = client.get("Custom Numbering Mode", mode)
        prefix = client.get("Custom Number Prefix", "").strip() or prefix

    if invoice_date is None:
        invoice_date = datetime.today()
    year = invoice_date.year

    invoices = st.session_state.invoices

    def extract_last_number(invoice_number):
        try:
            return int(str(invoice_number).split(separator)[-1])
        except:
            return None

    if mode == "simple":
        numbers = []
        for inv in invoices:
            inv_client_name = inv.get("Client", "")
            if client is not None and client.get("Use Custom Numbering", False):
                if inv_client_name != client.get("Company Name", ""):
                    continue

            inv_number = str(inv.get("Invoice Number", ""))
            if inv_number.startswith(f"{prefix}{separator}"):
                num = extract_last_number(inv_number)
                if num is not None:
                    numbers.append(num)

        next_num = max(numbers) + 1 if numbers else 1
        return f"{prefix}{separator}{next_num:0{digits}d}"

    elif mode == "yearly":
        year_tag = str(year)
        numbers = []

        for inv in invoices:
            inv_client_name = inv.get("Client", "")
            if client is not None and client.get("Use Custom Numbering", False):
                if inv_client_name != client.get("Company Name", ""):
                    continue

            inv_number = str(inv.get("Invoice Number", ""))
            if inv_number.startswith(f"{prefix}{separator}{year_tag}{separator}"):
                num = extract_last_number(inv_number)
                if num is not None:
                    numbers.append(num)

        next_num = max(numbers) + 1 if numbers else 1
        return f"{prefix}{separator}{year_tag}{separator}{next_num:0{digits}d}"

    return f"{prefix}{separator}0001"


# --- Ensure invoice status / due date fields exist ---
def ensure_invoice_fields():
    changed = False
    today = datetime.today().date()

    defaults = st.session_state.settings["invoice_defaults"]
    default_currency = defaults.get("currency", "AED")
    default_tax = defaults.get("tax_percentage", 0.0)
    default_terms = int(defaults.get("payment_terms_days", 30))

    valid_statuses = ["Draft", "Sent", "Overdue", "Paid", "Cancelled"]

    for inv in st.session_state.invoices:
        if "Due Date" not in inv:
            try:
                invoice_date = datetime.strptime(inv["Date"], "%d/%m/%Y").date()
                inv["Due Date"] = (invoice_date + timedelta(days=default_terms)).strftime("%d/%m/%Y")
            except:
                inv["Due Date"] = datetime.today().strftime("%d/%m/%Y")
            changed = True

        if "Status" not in inv:
            inv["Status"] = "Draft"
            changed = True

        if inv["Status"] not in valid_statuses:
            inv["Status"] = "Draft"
            changed = True

        if "Items" not in inv:
            inv["Items"] = [{"Job Name": "", "Job Number": "", "Amount": float(inv.get("Total", 0.0))}]
            changed = True

        if "Tax Percentage" not in inv:
            inv["Tax Percentage"] = default_tax
            changed = True

        if "Currency" not in inv:
            inv["Currency"] = default_currency
            changed = True

        if "Sent Date" not in inv:
            inv["Sent Date"] = ""
            changed = True

        if "Paid Date" not in inv:
            inv["Paid Date"] = ""
            changed = True

        if inv["Status"] not in ["Paid", "Cancelled"]:
            try:
                due_date = datetime.strptime(inv["Due Date"], "%d/%m/%Y").date()
                if inv["Status"] == "Sent" and due_date < today:
                    inv["Status"] = "Overdue"
                    changed = True
            except:
                pass

    if changed:
        save_json(INVOICES_FILE, st.session_state.invoices)


ensure_invoice_fields()


# --- PDF builder ---
def build_invoice_pdf(my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings):
    pdf = FPDF()
    pdf.add_page()

    business = settings["business_details"]
    display = settings["display_options"]
    branding = settings["branding"]

    header_top_y = 10
    left_x = 10
    logo_x = 155
    logo_w = 45

    logo_bottom_y = header_top_y
    logo_file = branding.get("invoice_logo_file", "")

    if display.get("show_logo", True) and logo_file and os.path.exists(logo_file):
        try:
            with Image.open(logo_file) as img:
                img_width_px, img_height_px = img.size

            if img_width_px > 0:
                logo_h = logo_w * (img_height_px / img_width_px)
            else:
                logo_h = 20

            pdf.image(logo_file, x=logo_x, y=header_top_y, w=logo_w)
            logo_bottom_y = header_top_y + logo_h
        except:
            pass

    pdf.set_xy(left_x, header_top_y)
    pdf.set_font("Arial", "B", 20)
    pdf.cell(0, 10, my_details.get("Name", ""), ln=True)

    pdf.set_font("Arial", "", 11)
    if display.get("show_address", True) and my_details.get("Address", ""):
        pdf.multi_cell(0, 5, my_details.get("Address", ""))

    extra_lines = []
    if display.get("show_phone", True) and business.get("phone", ""):
        extra_lines.append(f"Phone: {business['phone']}")
    if display.get("show_email", True) and business.get("email", ""):
        extra_lines.append(f"Email: {business['email']}")
    if display.get("show_vat_number", True) and business.get("vat_number", ""):
        extra_lines.append(f"VAT / Tax No: {business['vat_number']}")

    if extra_lines:
        pdf.multi_cell(0, 5, "\n".join(extra_lines))

    text_bottom_y = pdf.get_y()
    header_bottom_y = max(text_bottom_y, logo_bottom_y)
    pdf.set_y(header_bottom_y + 5)

    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "INVOICE", ln=True, align="R")

    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 5, f"Invoice Number: {invoice_number}", ln=True, align="R")
    pdf.cell(0, 5, f"Date: {invoice_date.strftime('%d/%m/%Y')}", ln=True, align="R")

    if display.get("show_payment_terms", True):
        pdf.cell(0, 5, f"Due Date: {due_date.strftime('%d/%m/%Y')}", ln=True, align="R")
        terms_days = settings["invoice_defaults"].get("payment_terms_days", 30)
        pdf.cell(0, 5, f"Payment Terms: {terms_days} days", ln=True, align="R")

    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 5, "Bill To:", ln=True)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 5, f"{client['Company Name']} ({client['Contact Person']})", ln=True)
    pdf.multi_cell(0, 5, client["Address"])
    pdf.ln(5)

    pdf.set_fill_color(200, 200, 200)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(80, 10, "Job Name", 1, 0, "C", 1)
    pdf.cell(40, 10, "Job Number", 1, 0, "C", 1)
    pdf.cell(40, 10, f"Amount ({currency})", 1, 1, "C", 1)

    pdf.set_font("Arial", "", 12)
    fill = False
    subtotal = 0
    for item in items:
        amount_value = float(item.get("Amount", 0.0))
        pdf.set_fill_color(240, 240, 240) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(80, 10, str(item.get("Job Name", "")), 1, 0, "L", fill)
        pdf.cell(40, 10, str(item.get("Job Number", "")), 1, 0, "C", fill)
        pdf.cell(40, 10, f"{amount_value:,.2f}", 1, 1, "R", fill)
        subtotal += amount_value
        fill = not fill

    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(120, 10, "Subtotal", 1, 0, "R", 1)
    pdf.cell(40, 10, f"{subtotal:,.2f}", 1, 1, "R", 1)

    tax_amount = subtotal * (tax_percent / 100)
    if tax_amount > 0:
        pdf.cell(120, 10, f"Tax ({tax_percent}%)", 1, 0, "R", 1)
        pdf.cell(40, 10, f"{tax_amount:,.2f}", 1, 1, "R", 1)

    total = subtotal + tax_amount
    pdf.cell(120, 10, "Total", 1, 0, "R", 1)
    pdf.cell(40, 10, f"{total:,.2f} {currency}", 1, 1, "R", 1)

    pdf.ln(10)

    if display.get("show_bank_details", True):
        bank_lines = []
        if my_details.get("Account Number", ""):
            bank_lines.append(f"Account: {my_details.get('Account Number', '')}")
        if my_details.get("Sort Code", ""):
            bank_lines.append(f"Sort Code: {my_details.get('Sort Code', '')}")
        if my_details.get("SWIFT", ""):
            bank_lines.append(f"SWIFT: {my_details.get('SWIFT', '')}")

        if bank_lines:
            pdf.set_font("Arial", "I", 10)
            pdf.multi_cell(0, 5, "Bank Details:\n" + "\n".join(bank_lines))
            pdf.ln(5)

    footer_text = branding.get("footer_text", "Thank you for your business!")
    if footer_text:
        pdf.set_font("Arial", "I", 10)
        pdf.multi_cell(0, 5, footer_text)

    return pdf, total


def generate_invoice_pdf(my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings):
    pdf, total = build_invoice_pdf(
        my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings
    )

    invoices_folder = "invoices_pdf"
    if not os.path.exists(invoices_folder):
        os.makedirs(invoices_folder)

    safe_company = client["Company Name"].replace(" ", "_").replace("/", "_")
    filename = f"Invoice_{invoice_number}_{safe_company}.pdf"
    filepath = os.path.join(invoices_folder, filename)
    pdf.output(filepath)
    return filepath, total


def generate_invoice_pdf_bytes(my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings):
    pdf, total = build_invoice_pdf(
        my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings
    )
    pdf_bytes = pdf.output(dest="S").encode("latin-1")
    return pdf_bytes, total


def show_pdf_preview(pdf_bytes):
    pdf_viewer(pdf_bytes, width="100%")


# --- My Clients Page ---
@st.dialog("Client Details")
def show_client_dialog(idx):
    if idx is None or idx >= len(st.session_state.clients):
        st.warning("No client selected.")
        st.session_state.client_dialog_idx = None
        st.session_state.client_dialog_edit_mode = False
        return

    client = st.session_state.clients[idx]
    edit_mode = st.session_state.client_dialog_edit_mode

    button_col_left, button_col_right = st.columns([6, 2])

    with button_col_right:
        if edit_mode:
            if st.button("Cancel Edit", use_container_width=True, key=f"dialog_cancel_edit_{idx}"):
                st.session_state.client_dialog_idx = None
                st.session_state.client_dialog_edit_mode = False
                st.rerun()
        else:
            if st.button("Edit Client", use_container_width=True, key=f"dialog_edit_client_{idx}"):
                st.session_state.client_dialog_idx = idx
                st.session_state.client_dialog_edit_mode = True
                st.rerun()

    st.markdown("<div style='margin-top:-10px;'></div>", unsafe_allow_html=True)
    st.markdown("---")

    if edit_mode:
        with st.form(key=f"client_edit_form_{idx}", border=False):
            form_left, form_right = st.columns([1, 1])

            with form_left:
                company = st.text_input("Company Name", client.get("Company Name", ""))
                contact = st.text_input("Contact Person", client.get("Contact Person", ""))
                email = st.text_input("Email Address", client.get("Email", ""))
                phone = st.text_input("Phone Number", client.get("Phone", ""))
                invoice_email = st.text_input("Invoice Email", client.get("Invoice Email", ""))
                payment_terms = st.number_input(
                    "Payment Terms (days)",
                    min_value=1,
                    value=int(client.get("Payment Terms", 30))
                )
                vat_number = st.text_input("VAT / Tax Number", client.get("VAT Number", ""))

            with form_right:
                currency_options = ["", "AED", "USD", "EUR", "GBP", "INR", "JPY", "CHF", "AUD", "CAD"]
                current_currency = client.get("Default Currency", "")
                if current_currency not in currency_options:
                    current_currency = ""

                default_currency = st.selectbox(
                    "Default Currency",
                    currency_options,
                    index=currency_options.index(current_currency)
                )

                use_custom_numbering = st.checkbox(
                    "Use Custom Numbering For This Client",
                    value=client.get("Use Custom Numbering", False)
                )

                custom_mode_options = ["simple", "yearly"]
                current_custom_mode = client.get("Custom Numbering Mode", "simple")
                if current_custom_mode not in custom_mode_options:
                    current_custom_mode = "simple"

                custom_numbering_mode = st.selectbox(
                    "Client Numbering Mode",
                    custom_mode_options,
                    index=custom_mode_options.index(current_custom_mode)
                )

                custom_number_prefix = st.text_input(
                    "Client Number Prefix",
                    client.get("Custom Number Prefix", "")
                )

                sep = st.session_state.settings.get("invoice_numbering", {}).get("separator", "-")
                digits = int(st.session_state.settings.get("invoice_numbering", {}).get("digits", 4))
                preview_year = datetime.today().year
                preview_prefix = custom_number_prefix.strip() or st.session_state.settings.get("invoice_numbering", {}).get("prefix", "INV")

                if custom_numbering_mode == "simple":
                    preview = f"{preview_prefix}{sep}{1:0{digits}d}"
                else:
                    preview = f"{preview_prefix}{sep}{preview_year}{sep}{1:0{digits}d}"

                if use_custom_numbering:
                    st.caption(f"Preview: {preview}")
                else:
                    st.caption("Client custom numbering is off. Default app numbering will be used.")

            st.markdown("---")
            address = st.text_area("Address", client.get("Address", ""), height=120)
            notes = st.text_area("Notes", client.get("Notes", ""), height=160)

            st.markdown("---")
            save_col1, save_col2 = st.columns(2)

            with save_col1:
                save_changes = st.form_submit_button("Save Changes", use_container_width=True)
            with save_col2:
                close_without_save = st.form_submit_button("Close", use_container_width=True)

            if save_changes:
                st.session_state.clients[idx] = {
                    "Company Name": company.strip(),
                    "Contact Person": contact.strip(),
                    "Email": email.strip(),
                    "Phone": phone.strip(),
                    "Invoice Email": invoice_email.strip(),
                    "Payment Terms": int(payment_terms),
                    "VAT Number": vat_number.strip(),
                    "Default Currency": default_currency.strip(),
                    "Use Custom Numbering": bool(use_custom_numbering),
                    "Custom Numbering Mode": custom_numbering_mode if use_custom_numbering else "",
                    "Custom Number Prefix": custom_number_prefix.strip() if use_custom_numbering else "",
                    "Address": address.strip(),
                    "Notes": notes.strip()
                }
                save_json(CLIENTS_FILE, st.session_state.clients)
                st.session_state.client_dialog_idx = None
                st.session_state.client_dialog_edit_mode = False
                st.rerun()

            if close_without_save:
                st.session_state.client_dialog_idx = None
                st.session_state.client_dialog_edit_mode = False
                st.rerun()

    else:
        form_left, form_right = st.columns([1, 1])

        with form_left:
            st.text_input("Company Name", client.get("Company Name", ""), disabled=True)
            st.text_input("Contact Person", client.get("Contact Person", ""), disabled=True)
            st.text_input("Email Address", client.get("Email", ""), disabled=True)
            st.text_input("Phone Number", client.get("Phone", ""), disabled=True)
            st.text_input("Invoice Email", client.get("Invoice Email", ""), disabled=True)
            st.number_input(
                "Payment Terms (days)",
                min_value=1,
                value=int(client.get("Payment Terms", 30)),
                disabled=True
            )
            st.text_input("VAT / Tax Number", client.get("VAT Number", ""), disabled=True)

        with form_right:
            st.text_input("Default Currency", client.get("Default Currency", ""), disabled=True)
            st.checkbox(
                "Use Custom Numbering For This Client",
                value=client.get("Use Custom Numbering", False),
                disabled=True
            )
            st.text_input("Client Numbering Mode", client.get("Custom Numbering Mode", ""), disabled=True)
            st.text_input("Client Number Prefix", client.get("Custom Number Prefix", ""), disabled=True)

        st.markdown("---")
        st.text_area("Address", client.get("Address", ""), height=120, disabled=True)
        st.text_area("Notes", client.get("Notes", ""), height=160, disabled=True)

        st.markdown("---")
        if st.button("Close", use_container_width=True, key=f"dialog_close_client_{idx}"):
            st.session_state.client_dialog_idx = None
            st.session_state.client_dialog_edit_mode = False
            st.rerun()


# --- Settings Page ---
def settings_page():
    page_header(
        "Settings",
        back_label="Back to Dashboard",
        back_page="main",
        help_text="Manage your business details, invoice defaults, branding, display options, and numbering."
    )

    business = st.session_state.settings["business_details"]
    defaults = st.session_state.settings["invoice_defaults"]
    numbering = st.session_state.settings.get("invoice_numbering", {})
    display = st.session_state.settings["display_options"]
    branding = st.session_state.settings["branding"]

    left_col, spacer_col, right_col = st.columns([1, 0.08, 1])

    with left_col:
        st.subheader("Business Details")
        business_name = st.text_input("Business Name", business.get("name", ""))
        business_address = st.text_area("Business Address", business.get("address", ""), height=120)
        business_phone = st.text_input("Phone Number", business.get("phone", ""))
        business_email = st.text_input("Email Address", business.get("email", ""))
        business_vat = st.text_input("Company Tax / VAT Number", business.get("vat_number", ""))

        st.markdown("---")
        st.subheader("Bank Details")
        account_number = st.text_input("Account Number", business.get("account_number", ""))
        sort_code = st.text_input("Sort Code", business.get("sort_code", ""))
        swift = st.text_input("SWIFT", business.get("swift", ""))

    with spacer_col:
        st.empty()

    with right_col:
        st.subheader("Invoice Defaults")
        currency_options = ["AED", "USD", "EUR", "GBP", "INR", "JPY", "CHF", "AUD", "CAD"]
        current_currency = defaults.get("currency", "AED")
        if current_currency not in currency_options:
            current_currency = "AED"

        default_currency = st.selectbox(
            "Default Currency",
            currency_options,
            index=currency_options.index(current_currency)
        )
        default_tax = st.number_input(
            "Default Tax Percentage",
            min_value=0.0,
            value=float(defaults.get("tax_percentage", 0.0))
        )
        payment_terms_days = st.number_input(
            "Default Payment Terms (days)",
            min_value=1,
            value=int(defaults.get("payment_terms_days", 30))
        )

        st.markdown("---")
        st.subheader("Invoice Numbering")

        numbering_mode_options = ["simple", "yearly"]
        current_mode = numbering.get("mode", "simple")
        if current_mode not in numbering_mode_options:
            current_mode = "simple"

        numbering_mode = st.selectbox(
            "Default Numbering Mode",
            numbering_mode_options,
            index=numbering_mode_options.index(current_mode)
        )
        numbering_prefix = st.text_input("Default Number Prefix", numbering.get("prefix", "INV"))
        numbering_digits = st.number_input(
            "Number of Digits",
            min_value=2,
            max_value=8,
            value=int(numbering.get("digits", 4))
        )

        separator_options = ["-", "/", "_", "."]
        current_separator = numbering.get("separator", "-")
        if current_separator not in separator_options:
            current_separator = "-"

        numbering_separator = st.selectbox(
            "Separator",
            separator_options,
            index=separator_options.index(current_separator)
        )

        preview_prefix = numbering_prefix.strip() or "INV"
        preview_year = datetime.today().year

        if numbering_mode == "simple":
            numbering_preview = f"{preview_prefix}{numbering_separator}{1:0{int(numbering_digits)}d}"
        else:
            numbering_preview = f"{preview_prefix}{numbering_separator}{preview_year}{numbering_separator}{1:0{int(numbering_digits)}d}"

        st.caption(f"Preview: {numbering_preview}")

        st.markdown("---")
        st.subheader("Display Options")
        show_logo = st.checkbox("Show Logo on Invoice", value=display.get("show_logo", True))
        show_address = st.checkbox("Show Address on Invoice", value=display.get("show_address", True))
        show_phone = st.checkbox("Show Phone on Invoice", value=display.get("show_phone", True))
        show_email = st.checkbox("Show Email on Invoice", value=display.get("show_email", True))
        show_vat = st.checkbox("Show Tax / VAT Number on Invoice", value=display.get("show_vat_number", True))
        show_bank = st.checkbox("Show Bank Details on Invoice", value=display.get("show_bank_details", True))
        show_terms = st.checkbox("Show Payment Terms on Invoice", value=display.get("show_payment_terms", True))

        st.markdown("---")
        st.subheader("Branding")
        current_invoice_logo_file = branding.get("invoice_logo_file", "")
        footer_text = st.text_area(
            "Invoice Footer Text",
            branding.get("footer_text", "Thank you for your business!"),
            height=100
        )
        invoice_logo_file_input = st.text_input("Invoice Logo Filename / Path", current_invoice_logo_file)
        uploaded_logo = st.file_uploader("Upload Invoice Logo (PNG/JPG)", type=["png", "jpg", "jpeg"])

        if uploaded_logo is not None:
            st.info("A new invoice logo has been selected. Click 'Save Settings' to save it.")

    st.markdown("---")
    action_col1, action_col2, action_col3 = st.columns([1, 1, 2])
    with action_col1:
        save_clicked = st.button("Save Settings", use_container_width=True)
    with action_col2:
        st.empty()

    if save_clicked:
        saved_invoice_logo_file = invoice_logo_file_input

        if uploaded_logo is not None:
            safe_name = uploaded_logo.name.replace(" ", "_")
            saved_invoice_logo_file = safe_name
            with open(saved_invoice_logo_file, "wb") as f:
                f.write(uploaded_logo.getbuffer())

        st.session_state.settings = {
            "business_details": {
                "name": business_name,
                "address": business_address,
                "phone": business_phone,
                "email": business_email,
                "vat_number": business_vat,
                "account_number": account_number,
                "sort_code": sort_code,
                "swift": swift
            },
            "invoice_defaults": {
                "currency": default_currency,
                "tax_percentage": default_tax,
                "payment_terms_days": payment_terms_days
            },
            "invoice_numbering": {
                "mode": numbering_mode,
                "prefix": numbering_prefix.strip() or "INV",
                "digits": int(numbering_digits),
                "separator": numbering_separator
            },
            "display_options": {
                "show_logo": show_logo,
                "show_address": show_address,
                "show_phone": show_phone,
                "show_email": show_email,
                "show_vat_number": show_vat,
                "show_bank_details": show_bank,
                "show_payment_terms": show_terms
            },
            "branding": {
                "invoice_logo_file": saved_invoice_logo_file,
                "footer_text": footer_text
            }
        }

        sync_my_details_from_settings()
        save_json(SETTINGS_FILE, st.session_state.settings)
        save_json(DETAILS_FILE, st.session_state.my_details)
        st.success("Settings saved!")


# --- Main Menu ---
def show_main_menu():
    top_left, top_right = st.columns([4, 1.3], vertical_alignment="top")

    with top_left:
        if os.path.exists(LOGO_FILE):
            with open(LOGO_FILE, "rb") as image_file:
                logo_base64 = base64.b64encode(image_file.read()).decode()

            st.markdown(
                f"""
                <div style="
                    height: 210px;
                    display: flex;
                    align-items: center;
                    justify-content: flex-start;
                    overflow: hidden;
                ">
                    <img src="data:image/png;base64,{logo_base64}"
                         style="
                             max-height: 210px;
                             max-width: 100%;
                             width: auto;
                             height: auto;
                             object-fit: contain;
                         ">
                </div>
                """,
                unsafe_allow_html=True
            )

    with top_right:
        st.button("Settings", use_container_width=True, on_click=lambda: st.session_state.update({"page": "settings"}))
        st.button("My Clients", use_container_width=True, on_click=lambda: st.session_state.update({"page": "my_clients"}))
        st.button("My Invoices", use_container_width=True, on_click=lambda: st.session_state.update({"page": "my_invoices"}))

    st.markdown("---")
    show_dashboard()


def my_clients_page():
    header_left, header_right = st.columns([6, 2])

    with header_left:
        st.title("My Clients")
        st.caption("Manage your saved clients and keep your client list organised.")

    with header_right:
        st.button(
            "Back to Main Menu",
            use_container_width=True,
            on_click=lambda: st.session_state.update({"page": "main"})
        )
        st.button(
            "Add Client",
            use_container_width=True,
            on_click=lambda: st.session_state.update({"page": "add_client"})
        )

    st.markdown("---")

    if not st.session_state.clients:
        st.info("No clients yet.")
        return

    st.subheader("Clients Table")

    df = pd.DataFrame(st.session_state.clients).copy()

    if "Email" not in df.columns:
        df["Email"] = ""
    if "Phone" not in df.columns:
        df["Phone"] = ""
    if "Invoice Email" not in df.columns:
        df["Invoice Email"] = ""
    if "Use Custom Numbering" not in df.columns:
        df["Use Custom Numbering"] = False
    if "Custom Numbering Mode" not in df.columns:
        df["Custom Numbering Mode"] = ""
    if "Custom Number Prefix" not in df.columns:
        df["Custom Number Prefix"] = ""
    if "Payment Terms" not in df.columns:
        df["Payment Terms"] = 30
    if "Notes" not in df.columns:
        df["Notes"] = ""
    if "VAT Number" not in df.columns:
        df["VAT Number"] = ""
    if "Default Currency" not in df.columns:
        df["Default Currency"] = ""

    table_df = df[[
        "Company Name",
        "Contact Person",
        "Email",
        "Phone",
        "Invoice Email",
        "Payment Terms"
    ]].copy()

    table_df["Select"] = False

    edited_df = st.data_editor(
        table_df,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        key="clients_table_editor"
    )

    selected_rows = edited_df[edited_df["Select"] == True]

    selected_companies = sorted(selected_rows["Company Name"].tolist())
    previous_selected_companies = st.session_state.get("previous_selected_clients", [])

    if selected_companies != previous_selected_companies:
        st.session_state.client_dialog_idx = None
        st.session_state.client_dialog_edit_mode = False
        st.session_state.previous_selected_clients = selected_companies

    st.markdown("---")
    st.subheader("Selected Client Actions")

    selected_count = len(selected_rows)
    single_selected = selected_count == 1

    if selected_count == 0:
        st.caption("Select one client from the table to view, edit, or delete.")
    elif selected_count == 1:
        st.caption("1 client selected.")
    else:
        st.caption(f"{selected_count} clients selected.")

    action_col1, action_col2, action_col3, action_col4 = st.columns([1, 1, 1, 3])

    with action_col1:
        if st.button("View Selected Client", use_container_width=True, disabled=not single_selected):
            selected_company = selected_rows.iloc[0]["Company Name"]
            for idx, client in enumerate(st.session_state.clients):
                if client["Company Name"] == selected_company:
                    st.session_state.client_dialog_idx = idx
                    st.session_state.client_dialog_edit_mode = False
                    st.rerun()

    with action_col2:
        if st.button("Edit Selected Client", use_container_width=True, disabled=not single_selected):
            selected_company = selected_rows.iloc[0]["Company Name"]
            for idx, client in enumerate(st.session_state.clients):
                if client["Company Name"] == selected_company:
                    st.session_state.client_dialog_idx = idx
                    st.session_state.client_dialog_edit_mode = True
                    st.rerun()

    with action_col3:
        if st.button("Delete Selected Client", use_container_width=True, disabled=not single_selected):
            selected_company = selected_rows.iloc[0]["Company Name"]
            st.session_state.clients = [
                client for client in st.session_state.clients
                if client["Company Name"] != selected_company
            ]
            st.session_state.client_dialog_idx = None
            st.session_state.client_dialog_edit_mode = False
            save_json(CLIENTS_FILE, st.session_state.clients)
            st.rerun()

    if st.session_state.client_dialog_idx is not None:
        show_client_dialog(st.session_state.client_dialog_idx)


# --- Add Client Page ---
def add_client_page():
    page_header(
        "Add New Client",
        back_label="Back to Clients",
        back_page="my_clients",
        help_text="Create a new client record to use for future invoices."
    )

    form_col1, form_col2, form_col3 = st.columns([1.2, 0.1, 1.7])

    with form_col1:
        company = st.text_input("Company Name")
        contact = st.text_input("Contact Person")
        email = st.text_input("Email Address")
        phone = st.text_input("Phone Number")
        invoice_email = st.text_input("Invoice Email")
        payment_terms = st.number_input("Payment Terms (days)", min_value=1, value=30)
        vat_number = st.text_input("VAT / Tax Number")

    with form_col3:
        currency_options = ["", "AED", "USD", "EUR", "GBP", "INR", "JPY", "CHF", "AUD", "CAD"]
        default_currency = st.selectbox("Default Currency", currency_options, index=0)

        use_custom_numbering = st.checkbox("Use Custom Numbering For This Client", value=False)
        custom_mode_options = ["simple", "yearly"]
        custom_numbering_mode = st.selectbox(
            "Client Numbering Mode",
            custom_mode_options,
            index=0
        )
        custom_number_prefix = st.text_input(
            "Client Number Prefix",
            value=""
        )
        if use_custom_numbering:
            sep = st.session_state.settings.get("invoice_numbering", {}).get("separator", "-")
            digits = int(st.session_state.settings.get("invoice_numbering", {}).get("digits", 4))
            preview_year = datetime.today().year
            preview_prefix = custom_number_prefix.strip() or st.session_state.settings.get("invoice_numbering", {}).get("prefix", "INV")

            if custom_numbering_mode == "simple":
                preview = f"{preview_prefix}{sep}{1:0{digits}d}"
            else:
                preview = f"{preview_prefix}{sep}{preview_year}{sep}{1:0{digits}d}"

            st.caption(f"Preview: {preview}")

        address = st.text_area("Address", height=120)
        notes = st.text_area("Notes", height=120)

    if st.button("Save Client", use_container_width=True):
        if company.strip() and contact.strip() and address.strip():
            st.session_state.clients.append({
                "Company Name": company.strip(),
                "Contact Person": contact.strip(),
                "Email": email.strip(),
                "Phone": phone.strip(),
                "Invoice Email": invoice_email.strip(),
                "Payment Terms": int(payment_terms),
                "VAT Number": vat_number.strip(),
                "Default Currency": default_currency.strip(),
                "Use Custom Numbering": bool(use_custom_numbering),
                "Custom Numbering Mode": custom_numbering_mode if use_custom_numbering else "",
                "Custom Number Prefix": custom_number_prefix.strip() if use_custom_numbering else "",
                "Address": address.strip(),
                "Notes": notes.strip()
            })
            save_json(CLIENTS_FILE, st.session_state.clients)
            st.success("Client added!")
            st.session_state.client_dialog_idx = len(st.session_state.clients) - 1
            st.session_state.client_dialog_edit_mode = False
            st.session_state.page = "my_clients"
            st.rerun()
        else:
            st.warning("Please complete Company Name, Contact Person, and Address.")


# --- Create Invoice Page ---
def create_invoice_page():
    page_header(
        "Generate New Invoice",
        back_label="Back to Dashboard",
        back_page="main",
        help_text="Enter invoice details on the left and review the live preview on the right."
    )

    if not st.session_state.my_details:
        st.warning("Please enter your details first in Settings.")
        return
    if not st.session_state.clients:
        st.warning("Please add clients first in 'My Clients'.")
        return

    input_col, spacer_col, preview_col = st.columns([1, 0.08, 1.1])

    with input_col:
        client_names = [f"{c['Company Name']} ({c['Contact Person']})" for c in st.session_state.clients]
        selected_idx = st.selectbox("Select Client", range(len(client_names)), format_func=lambda x: client_names[x])
        client = st.session_state.clients[selected_idx]

        defaults = st.session_state.settings["invoice_defaults"]
        default_currency = client.get("Default Currency", "") or defaults.get("currency", "AED")
        default_tax = float(defaults.get("tax_percentage", 0.0))
        default_terms = int(client.get("Payment Terms", defaults.get("payment_terms_days", 30)))

        date_col1, date_col2 = st.columns(2)
        with date_col1:
            invoice_date = st.date_input("Invoice Date", value=datetime.today())
        with date_col2:
            due_date = st.date_input("Due Date", value=datetime.today() + timedelta(days=default_terms))

        invoice_number = get_next_invoice_number(client=client, invoice_date=invoice_date)
        st.text_input("Invoice Number", value=invoice_number, disabled=True)

        st.subheader("Line Items")
        items = []
        num_items = st.number_input("Number of Line Items", min_value=1, max_value=20, value=1)

        for i in range(num_items):
            st.markdown(f"**Item {i+1}**")
            item_col1, item_col2, item_col3 = st.columns([2, 1.4, 1])
            with item_col1:
                job_name = st.text_input(f"Job Name {i+1}")
            with item_col2:
                job_number = st.text_input(f"Job Number {i+1}")
            with item_col3:
                amount = st.number_input(f"Amount {i+1}", min_value=0.0, value=0.0)
            items.append({"Job Name": job_name, "Job Number": job_number, "Amount": amount})

        tax_col1, tax_col2 = st.columns(2)
        with tax_col1:
            tax_percent = st.number_input("Tax Percentage", min_value=0.0, value=default_tax)
        with tax_col2:
            currency_options = ["AED", "USD", "EUR", "GBP", "INR", "JPY", "CHF", "AUD", "CAD"]
            if default_currency not in currency_options:
                default_currency = "AED"
            currency = st.selectbox("Currency", currency_options, index=currency_options.index(default_currency))

        st.markdown("---")
        if st.button("Generate Invoice", use_container_width=True):
            filename, total = generate_invoice_pdf(
                st.session_state.my_details,
                client,
                invoice_number,
                items,
                tax_percent,
                currency,
                invoice_date,
                due_date,
                st.session_state.settings
            )

            st.session_state.invoices.append({
                "Invoice Number": invoice_number,
                "Client": client["Company Name"],
                "Filename": filename,
                "Date": invoice_date.strftime("%d/%m/%Y"),
                "Due Date": due_date.strftime("%d/%m/%Y"),
                "Status": "Draft",
                "Items": items,
                "Tax Percentage": tax_percent,
                "Currency": currency,
                "Total": total
            })
            save_json(INVOICES_FILE, st.session_state.invoices)
            st.success(f"Invoice generated: {filename}")
            st.session_state.page = "main"

    with spacer_col:
        st.empty()

    with preview_col:
        preview_pdf_bytes, preview_total = generate_invoice_pdf_bytes(
            st.session_state.my_details,
            client,
            invoice_number,
            items,
            tax_percent,
            currency,
            invoice_date,
            due_date,
            st.session_state.settings
        )

        show_pdf_preview(preview_pdf_bytes)
        st.metric("Preview Total", f"{preview_total:,.2f} {currency}")


# --- Edit Invoice Page ---
def edit_invoice_page():
    page_header(
        "Edit Invoice",
        back_label="Back to My Invoices",
        back_page="my_invoices",
        help_text="Update invoice details on the left and review the live preview on the right."
    )

    if st.session_state.edit_invoice_idx is None:
        st.warning("No invoice selected.")
        st.session_state.page = "my_invoices"
        return

    idx = st.session_state.edit_invoice_idx
    invoice = st.session_state.invoices[idx]

    input_col, spacer_col, preview_col = st.columns([1, 0.08, 1.1])

    with input_col:
        client_names = [f"{c['Company Name']} ({c['Contact Person']})" for c in st.session_state.clients]

        current_client_idx = 0
        for i, c in enumerate(st.session_state.clients):
            if c["Company Name"] == invoice["Client"]:
                current_client_idx = i
                break

        selected_idx = st.selectbox(
            "Select Client",
            range(len(client_names)),
            index=current_client_idx,
            format_func=lambda x: client_names[x]
        )
        client = st.session_state.clients[selected_idx]

        invoice_number = invoice["Invoice Number"]
        st.text_input("Invoice Number", value=invoice_number, disabled=True)

        try:
            invoice_date_default = datetime.strptime(invoice["Date"], "%d/%m/%Y").date()
        except:
            invoice_date_default = datetime.today().date()

        try:
            due_date_default = datetime.strptime(invoice.get("Due Date", invoice["Date"]), "%d/%m/%Y").date()
        except:
            due_date_default = invoice_date_default + timedelta(days=30)

        date_col1, date_col2 = st.columns(2)
        with date_col1:
            invoice_date = st.date_input("Invoice Date", value=invoice_date_default)
        with date_col2:
            due_date = st.date_input("Due Date", value=due_date_default)

        status_options = ["Draft", "Sent", "Paid", "Overdue"]
        current_status = invoice.get("Status", "Draft")
        if current_status not in status_options:
            current_status = "Draft"

        status = st.selectbox("Status", status_options, index=status_options.index(current_status))

        st.subheader("Line Items")
        existing_items = invoice.get("Items", [])
        default_num_items = len(existing_items) if len(existing_items) > 0 else 1

        items = []
        num_items = st.number_input("Number of Line Items", min_value=1, max_value=20, value=default_num_items)

        for i in range(num_items):
            existing_item = existing_items[i] if i < len(existing_items) else {
                "Job Name": "",
                "Job Number": "",
                "Amount": 0.0
            }

            st.markdown(f"**Item {i+1}**")
            item_col1, item_col2, item_col3 = st.columns([2, 1.4, 1])
            with item_col1:
                job_name = st.text_input(
                    f"Job Name {i+1}",
                    value=existing_item.get("Job Name", ""),
                    key=f"edit_job_name_{i}"
                )
            with item_col2:
                job_number = st.text_input(
                    f"Job Number {i+1}",
                    value=existing_item.get("Job Number", ""),
                    key=f"edit_job_number_{i}"
                )
            with item_col3:
                amount = st.number_input(
                    f"Amount {i+1}",
                    min_value=0.0,
                    value=float(existing_item.get("Amount", 0.0)),
                    key=f"edit_amount_{i}"
                )

            items.append({
                "Job Name": job_name,
                "Job Number": job_number,
                "Amount": amount
            })

        tax_col1, tax_col2 = st.columns(2)
        with tax_col1:
            default_tax = float(invoice.get("Tax Percentage", st.session_state.settings["invoice_defaults"].get("tax_percentage", 0.0)))
            tax_percent = st.number_input("Tax Percentage", min_value=0.0, value=default_tax)

        with tax_col2:
            currency_options = ["AED", "USD", "EUR", "GBP", "INR", "JPY", "CHF", "AUD", "CAD"]
            current_currency = invoice.get("Currency", st.session_state.settings["invoice_defaults"].get("currency", "AED"))
            if current_currency not in currency_options:
                current_currency = "AED"
            currency = st.selectbox("Currency", currency_options, index=currency_options.index(current_currency))

        st.markdown("---")
        if st.button("Save Invoice Changes", use_container_width=True):
            old_filepath = invoice.get("Filename", "")
            if old_filepath and os.path.exists(old_filepath):
                os.remove(old_filepath)

            filename, total = generate_invoice_pdf(
                st.session_state.my_details,
                client,
                invoice_number,
                items,
                tax_percent,
                currency,
                invoice_date,
                due_date,
                st.session_state.settings
            )

            st.session_state.invoices[idx] = {
                "Invoice Number": invoice_number,
                "Client": client["Company Name"],
                "Filename": filename,
                "Date": invoice_date.strftime("%d/%m/%Y"),
                "Due Date": due_date.strftime("%d/%m/%Y"),
                "Status": status,
                "Items": items,
                "Tax Percentage": tax_percent,
                "Currency": currency,
                "Total": total
            }

            save_json(INVOICES_FILE, st.session_state.invoices)
            st.success("Invoice updated!")
            st.session_state.page = "my_invoices"
            st.session_state.edit_invoice_idx = None
            st.rerun()

    with spacer_col:
        st.empty()

    with preview_col:
        preview_pdf_bytes, preview_total = generate_invoice_pdf_bytes(
            st.session_state.my_details,
            client,
            invoice_number,
            items,
            tax_percent,
            currency,
            invoice_date,
            due_date,
            st.session_state.settings
        )

        show_pdf_preview(preview_pdf_bytes)
        st.metric("Preview Total", f"{preview_total:,.2f} {currency}")


# --- Dashboard ---
def show_dashboard():
    st.subheader("Dashboard")

    if not st.session_state.invoices:
        st.info("No invoices yet.")
        return

    df = pd.DataFrame(st.session_state.invoices).copy()

    if "Total" not in df.columns:
        df["Total"] = 0.0
    if "Status" not in df.columns:
        df["Status"] = "Draft"
    if "Date" not in df.columns:
        df["Date"] = datetime.today().strftime("%d/%m/%Y")
    if "Paid Date" not in df.columns:
        df["Paid Date"] = ""

    df["Date_dt"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df["Paid_dt"] = pd.to_datetime(df["Paid Date"], format="%d/%m/%Y", errors="coerce")

    today = datetime.today()

    month_mask = (df["Date_dt"].dt.month == today.month) & (df["Date_dt"].dt.year == today.year)
    year_mask = df["Date_dt"].dt.year == today.year

    revenue_month = df.loc[month_mask, "Total"].sum()
    revenue_year = df.loc[year_mask, "Total"].sum()
    outstanding_revenue = df.loc[df["Status"].isin(["Sent", "Overdue"]), "Total"].sum()
    overdue_revenue = df.loc[df["Status"] == "Overdue", "Total"].sum()
    paid_revenue = df.loc[df["Status"] == "Paid", "Total"].sum()

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Revenue This Month", f"{revenue_month:,.2f}")
    metric_col2.metric("Revenue This Year", f"{revenue_year:,.2f}")
    metric_col3.metric("Outstanding Revenue", f"{outstanding_revenue:,.2f}")
    metric_col4.metric("Overdue Revenue", f"{overdue_revenue:,.2f}")

    st.markdown("---")

    outer_left, chart_left, middle_gap, chart_right, outer_right = st.columns([1.4, 1.2, 0.35, 1.2, 1.4])

    with chart_left:
        st.markdown("##### Invoice Status Breakdown")

        status_order = ["Draft", "Sent", "Overdue", "Paid", "Cancelled"]
        status_counts = df["Status"].value_counts().reindex(status_order, fill_value=0)
        status_counts = status_counts[status_counts > 0]

        if not status_counts.empty:
            fig1, ax1 = plt.subplots(figsize=(3.1, 2.6))
            ax1.pie(
                status_counts.values,
                labels=status_counts.index,
                autopct="%1.1f%%",
                startangle=90,
                wedgeprops=dict(width=0.40)
            )
            ax1.axis("equal")
            st.pyplot(fig1, width="content")
        else:
            st.info("No status data yet.")

    with chart_right:
        st.markdown("##### Top Clients by Revenue")

        revenue_by_client = df.groupby("Client")["Total"].sum().sort_values(ascending=False).head(5)

        if not revenue_by_client.empty and revenue_by_client.sum() > 0:
            fig2, ax2 = plt.subplots(figsize=(3.5, 2.6))
            ax2.barh(revenue_by_client.index[::-1], revenue_by_client.values[::-1])
            ax2.set_xlabel("Revenue")
            ax2.set_ylabel("")
            ax2.spines["top"].set_visible(False)
            ax2.spines["right"].set_visible(False)
            st.pyplot(fig2, width="content")
        else:
            st.info("No client revenue data yet.")

    st.markdown("---")

    outer_left, chart_left, middle_gap, chart_right, outer_right = st.columns([1.4, 1.2, 0.35, 1.2, 1.4])

    with chart_left:
        st.markdown("##### Outstanding vs Paid")

        compare_labels = ["Outstanding", "Paid"]
        compare_values = [outstanding_revenue, paid_revenue]

        if sum(compare_values) > 0:
            fig3, ax3 = plt.subplots(figsize=(3.1, 2.6))
            ax3.pie(
                compare_values,
                labels=compare_labels,
                autopct="%1.1f%%",
                startangle=90,
                wedgeprops=dict(width=0.40)
            )
            ax3.axis("equal")
            st.pyplot(fig3, width="content")
        else:
            st.info("No payment data yet.")

    with chart_right:
        st.markdown("##### Invoices Created per Month")

        invoices_df = df[df["Date_dt"].notna()].copy()

        if not invoices_df.empty:
            invoices_df["Month"] = invoices_df["Date_dt"].dt.to_period("M").astype(str)
            invoices_per_month = invoices_df.groupby("Month").size().sort_index()

            if not invoices_per_month.empty:
                fig4, ax4 = plt.subplots(figsize=(3.5, 2.6))
                ax4.bar(invoices_per_month.index, invoices_per_month.values)
                ax4.set_xlabel("Month")
                ax4.set_ylabel("Invoices")
                ax4.tick_params(axis="x", rotation=45)
                ax4.spines["top"].set_visible(False)
                ax4.spines["right"].set_visible(False)
                st.pyplot(fig4, width="content")
            else:
                st.info("No monthly invoice data yet.")
        else:
            st.info("No monthly invoice data yet.")


# --- My Invoices Page ---
def my_invoices_page():
    ensure_invoice_fields()

    header_left, header_right = st.columns([6, 2])

    with header_left:
        st.title("My Invoices")
        st.caption("Browse, track, and manage invoice progress from draft through to payment.")

    with header_right:
        st.button(
            "Back to Dashboard",
            use_container_width=True,
            on_click=lambda: st.session_state.update({"page": "main"})
        )
        st.button(
            "Generate New Invoice",
            use_container_width=True,
            on_click=lambda: st.session_state.update({"page": "create_invoice"})
        )

    st.markdown("---")

    if not st.session_state.invoices:
        st.info("No invoices yet.")
        return

    today = datetime.today().date()
    df = pd.DataFrame(st.session_state.invoices).copy()

    df["Date_dt"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
    df["Due_dt"] = pd.to_datetime(df["Due Date"], format="%d/%m/%Y", errors="coerce")
    df["Sent_dt"] = pd.to_datetime(df.get("Sent Date", ""), format="%d/%m/%Y", errors="coerce")
    df["Paid_dt"] = pd.to_datetime(df.get("Paid Date", ""), format="%d/%m/%Y", errors="coerce")

    def calc_days(row):
        status = row.get("Status", "")
        due_dt = row.get("Due_dt")
        if pd.isna(due_dt):
            return ""

        due_date = due_dt.date()

        if status == "Draft":
            return ""
        if status == "Paid":
            paid_dt = row.get("Paid_dt")
            if pd.notna(paid_dt) and pd.notna(row.get("Date_dt")):
                return f"Paid in {(paid_dt.date() - row['Date_dt'].date()).days}d"
            return ""
        if status == "Cancelled":
            return ""
        if status == "Overdue":
            days = (today - due_date).days
            return f"{days} day(s) overdue"
        if status == "Sent":
            days = (due_date - today).days
            if days >= 0:
                return f"Due in {days} day(s)"
            return f"{abs(days)} day(s) overdue"
        return ""

    df["Tracking"] = df.apply(calc_days, axis=1)

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        search = st.text_input("Search Invoice Number")
    with filter_col2:
        clients = ["All"] + sorted(df["Client"].dropna().unique().tolist())
        client_filter = st.selectbox("Filter by Client", clients)
    with filter_col3:
        status_filter = st.selectbox("Filter by Status", ["All", "Draft", "Sent", "Overdue", "Paid", "Cancelled"])
    with filter_col4:
        ageing_filter = st.selectbox("Quick View", ["All", "Outstanding", "Overdue", "Paid", "Cancelled"])

    filtered_df = df.copy()

    if search:
        filtered_df = filtered_df[filtered_df["Invoice Number"].astype(str).str.contains(search, case=False, na=False)]
    if client_filter != "All":
        filtered_df = filtered_df[filtered_df["Client"] == client_filter]
    if status_filter != "All":
        filtered_df = filtered_df[filtered_df["Status"] == status_filter]
    if ageing_filter == "Outstanding":
        filtered_df = filtered_df[filtered_df["Status"].isin(["Sent", "Overdue"])]
    elif ageing_filter == "Overdue":
        filtered_df = filtered_df[filtered_df["Status"] == "Overdue"]
    elif ageing_filter == "Paid":
        filtered_df = filtered_df[filtered_df["Status"] == "Paid"]
    elif ageing_filter == "Cancelled":
        filtered_df = filtered_df[filtered_df["Status"] == "Cancelled"]

    active_df = filtered_df[filtered_df["Status"] != "Cancelled"]

    stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)
    stats_col1.metric("Filtered Total", f"{active_df['Total'].sum():,.2f}")
    stats_col2.metric("Outstanding", f"{filtered_df[filtered_df['Status'].isin(['Sent', 'Overdue'])]['Total'].sum():,.2f}")
    stats_col3.metric("Overdue", f"{filtered_df[filtered_df['Status'] == 'Overdue']['Total'].sum():,.2f}")
    stats_col4.metric("Paid", f"{filtered_df[filtered_df['Status'] == 'Paid']['Total'].sum():,.2f}")

    st.markdown("---")
    st.subheader("Invoices Table")

    table_df = filtered_df[[
        "Invoice Number",
        "Client",
        "Date",
        "Due Date",
        "Status",
        "Tracking",
        "Total"
    ]].copy()

    status_icons = {
        "Draft": "⚪ Draft",
        "Sent": "🔵 Sent",
        "Overdue": "🔴 Overdue",
        "Paid": "🟢 Paid",
        "Cancelled": "🟠 Cancelled"
    }
    table_df["Status"] = table_df["Status"].map(status_icons).fillna(table_df["Status"])
    table_df["Select"] = False

    edited_df = st.data_editor(
        table_df,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        disabled=["Invoice Number", "Client", "Date", "Due Date", "Status", "Tracking", "Total"]
    )

    selected_rows = edited_df[edited_df["Select"] == True]
    selected_count = len(selected_rows)
    has_selection = selected_count > 0
    single_selected = selected_count == 1

    st.markdown("---")
    st.subheader("Selected Invoice Actions")

    if selected_count == 0:
        st.caption("Select one or more invoices from the table to enable actions.")
    elif selected_count == 1:
        st.caption("1 invoice selected.")
    else:
        st.caption(f"{selected_count} invoices selected.")

    row1_col1, row1_col2, row1_col3, row1_col4, row1_col5 = st.columns(5)

    with row1_col1:
        if st.button("Edit Selected", use_container_width=True, disabled=not single_selected):
            selected_invoice_number = selected_rows.iloc[0]["Invoice Number"]
            for idx, inv in enumerate(st.session_state.invoices):
                if inv["Invoice Number"] == selected_invoice_number:
                    st.session_state.edit_invoice_idx = idx
                    st.session_state.page = "edit_invoice"
                    st.rerun()

    with row1_col2:
        if st.button("Mark as Draft", use_container_width=True, disabled=not has_selection):
            for _, row in selected_rows.iterrows():
                for inv in st.session_state.invoices:
                    if inv["Invoice Number"] == row["Invoice Number"]:
                        inv["Status"] = "Draft"
                        inv["Sent Date"] = ""
                        inv["Paid Date"] = ""
            save_json(INVOICES_FILE, st.session_state.invoices)
            st.rerun()

    with row1_col3:
        if st.button("Mark as Sent", use_container_width=True, disabled=not has_selection):
            sent_today = datetime.today().strftime("%d/%m/%Y")
            for _, row in selected_rows.iterrows():
                for inv in st.session_state.invoices:
                    if inv["Invoice Number"] == row["Invoice Number"] and inv["Status"] != "Cancelled":
                        inv["Status"] = "Sent"
                        if not inv.get("Sent Date"):
                            inv["Sent Date"] = sent_today
                        inv["Paid Date"] = ""
            save_json(INVOICES_FILE, st.session_state.invoices)
            st.rerun()

    with row1_col4:
        if st.button("Mark as Paid", use_container_width=True, disabled=not has_selection):
            paid_today = datetime.today().strftime("%d/%m/%Y")
            for _, row in selected_rows.iterrows():
                for inv in st.session_state.invoices:
                    if inv["Invoice Number"] == row["Invoice Number"] and inv["Status"] != "Cancelled":
                        inv["Status"] = "Paid"
                        inv["Paid Date"] = paid_today
                        if not inv.get("Sent Date"):
                            inv["Sent Date"] = inv.get("Date", paid_today)
            save_json(INVOICES_FILE, st.session_state.invoices)
            st.rerun()

    with row1_col5:
        if st.button("Mark as Cancelled", use_container_width=True, disabled=not has_selection):
            for _, row in selected_rows.iterrows():
                for inv in st.session_state.invoices:
                    if inv["Invoice Number"] == row["Invoice Number"]:
                        inv["Status"] = "Cancelled"
                        inv["Paid Date"] = ""
            save_json(INVOICES_FILE, st.session_state.invoices)
            st.rerun()

    row2_col1, row2_col2, row2_col3 = st.columns([1, 1, 2])

    with row2_col1:
        if has_selection:
            selected_files = []
            for _, row in selected_rows.iterrows():
                invoice = df[df["Invoice Number"] == row["Invoice Number"]].iloc[0]
                filepath = invoice["Filename"]
                if os.path.exists(filepath):
                    selected_files.append(filepath)

            if len(selected_files) == 1:
                file_path = selected_files[0]
                with open(file_path, "rb") as f:
                    st.download_button(
                        "Download as PDF",
                        data=f.read(),
                        file_name=os.path.basename(file_path),
                        mime="application/pdf",
                        use_container_width=True
                    )
            elif len(selected_files) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    for file_path in selected_files:
                        zip_file.write(file_path, os.path.basename(file_path))
                zip_buffer.seek(0)

                st.download_button(
                    "Download as PDF",
                    data=zip_buffer.getvalue(),
                    file_name="selected_invoices.zip",
                    mime="application/zip",
                    use_container_width=True
                )
        else:
            st.button("Download as PDF", use_container_width=True, disabled=True)

    with row2_col2:
        if st.button("Delete Selected", use_container_width=True, disabled=not has_selection):
            st.session_state.confirm_delete_invoices = True

    if st.session_state.confirm_delete_invoices:
        st.warning("Are you sure you want to delete the selected invoice(s)? This cannot be undone.")

        confirm_col1, confirm_col2, confirm_col3 = st.columns([1, 1, 2])

        with confirm_col1:
            if st.button("Yes, Delete", use_container_width=True):
                selected_numbers = selected_rows["Invoice Number"].tolist()
                for inv in st.session_state.invoices:
                    if inv["Invoice Number"] in selected_numbers:
                        filepath = inv["Filename"]
                        if os.path.exists(filepath):
                            os.remove(filepath)

                st.session_state.invoices = [
                    inv for inv in st.session_state.invoices
                    if inv["Invoice Number"] not in selected_numbers
                ]

                save_json(INVOICES_FILE, st.session_state.invoices)
                st.session_state.confirm_delete_invoices = False
                st.rerun()

        with confirm_col2:
            if st.button("Cancel Delete", use_container_width=True):
                st.session_state.confirm_delete_invoices = False
                st.rerun()


# --- Navigation ---
if st.session_state.page == "main":
    _ = show_main_menu()
elif st.session_state.page == "my_clients":
    _ = my_clients_page()
elif st.session_state.page == "add_client":
    _ = add_client_page()
elif st.session_state.page == "create_invoice":
    _ = create_invoice_page()
elif st.session_state.page == "my_invoices":
    _ = my_invoices_page()
elif st.session_state.page == "edit_invoice":
    _ = edit_invoice_page()
elif st.session_state.page == "settings":
    _ = settings_page()
