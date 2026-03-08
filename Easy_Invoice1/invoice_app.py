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

st.set_page_config(layout="wide")

# --- File paths ---
DETAILS_FILE = "my_details.json"
CLIENTS_FILE = "clients.json"
INVOICES_FILE = "invoices.json"
SETTINGS_FILE = "settings.json"
LOGO_FILE = "logo.png"


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

if 'page' not in st.session_state:
    st.session_state.page = "main"
if 'edit_client_idx' not in st.session_state:
    st.session_state.edit_client_idx = None
if 'edit_invoice_idx' not in st.session_state:
    st.session_state.edit_invoice_idx = None
if 'confirm_delete_invoices' not in st.session_state:
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
def get_next_invoice_number():
    if not st.session_state.invoices:
        return "INV-0001"

    numbers = []
    for inv in st.session_state.invoices:
        try:
            num = int(str(inv["Invoice Number"]).replace("INV-", ""))
            numbers.append(num)
        except:
            pass

    next_num = max(numbers) + 1 if numbers else 1
    return f"INV-{next_num:04d}"


# --- Ensure invoice status / due date fields exist ---
def ensure_invoice_fields():
    changed = False
    today = datetime.today().date()

    defaults = st.session_state.settings["invoice_defaults"]
    default_currency = defaults.get("currency", "AED")
    default_tax = defaults.get("tax_percentage", 0.0)
    default_terms = int(defaults.get("payment_terms_days", 30))

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

        if "Status" in inv and inv["Status"] not in ["Draft", "Sent", "Paid", "Overdue"]:
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

        if inv["Status"] != "Paid":
            try:
                due_date = datetime.strptime(inv["Due Date"], "%d/%m/%Y").date()
                new_status = "Overdue" if (inv["Status"] == "Sent" and due_date < today) else inv["Status"]
                if inv["Status"] != new_status:
                    inv["Status"] = new_status
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

    # --- Dynamic header layout to prevent overlap ---
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
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 10, my_details.get("Name", ""), ln=True)

    pdf.set_font("Arial", '', 11)
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

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "INVOICE", ln=True, align='R')

    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 5, f"Invoice Number: {invoice_number}", ln=True, align='R')
    pdf.cell(0, 5, f"Date: {invoice_date.strftime('%d/%m/%Y')}", ln=True, align='R')

    if display.get("show_payment_terms", True):
        pdf.cell(0, 5, f"Due Date: {due_date.strftime('%d/%m/%Y')}", ln=True, align='R')
        terms_days = settings["invoice_defaults"].get("payment_terms_days", 30)
        pdf.cell(0, 5, f"Payment Terms: {terms_days} days", ln=True, align='R')

    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 5, "Bill To:", ln=True)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 5, f"{client['Company Name']} ({client['Contact Person']})", ln=True)
    pdf.multi_cell(0, 5, client['Address'])
    pdf.ln(5)

    # Table header
    pdf.set_fill_color(200, 200, 200)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(80, 10, "Job Name", 1, 0, 'C', 1)
    pdf.cell(40, 10, "Job Number", 1, 0, 'C', 1)
    pdf.cell(40, 10, f"Amount ({currency})", 1, 1, 'C', 1)

    # Table body
    pdf.set_font("Arial", '', 12)
    fill = False
    subtotal = 0
    for item in items:
        amount_value = float(item.get("Amount", 0.0))
        pdf.set_fill_color(240, 240, 240) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(80, 10, str(item.get("Job Name", "")), 1, 0, 'L', fill)
        pdf.cell(40, 10, str(item.get("Job Number", "")), 1, 0, 'C', fill)
        pdf.cell(40, 10, f"{amount_value:,.2f}", 1, 1, 'R', fill)
        subtotal += amount_value
        fill = not fill

    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(120, 10, "Subtotal", 1, 0, 'R', 1)
    pdf.cell(40, 10, f"{subtotal:,.2f}", 1, 1, 'R', 1)

    tax_amount = subtotal * (tax_percent / 100)
    if tax_amount > 0:
        pdf.cell(120, 10, f"Tax ({tax_percent}%)", 1, 0, 'R', 1)
        pdf.cell(40, 10, f"{tax_amount:,.2f}", 1, 1, 'R', 1)

    total = subtotal + tax_amount
    pdf.cell(120, 10, "Total", 1, 0, 'R', 1)
    pdf.cell(40, 10, f"{total:,.2f} {currency}", 1, 1, 'R', 1)

    pdf.ln(10)

    if display.get("show_bank_details", True):
        bank_lines = []
        if my_details.get('Account Number', ''):
            bank_lines.append(f"Account: {my_details.get('Account Number', '')}")
        if my_details.get('Sort Code', ''):
            bank_lines.append(f"Sort Code: {my_details.get('Sort Code', '')}")
        if my_details.get('SWIFT', ''):
            bank_lines.append(f"SWIFT: {my_details.get('SWIFT', '')}")

        if bank_lines:
            pdf.set_font("Arial", 'I', 10)
            pdf.multi_cell(0, 5, "Bank Details:\n" + "\n".join(bank_lines))
            pdf.ln(5)

    footer_text = branding.get("footer_text", "Thank you for your business!")
    if footer_text:
        pdf.set_font("Arial", 'I', 10)
        pdf.multi_cell(0, 5, footer_text)

    return pdf, total


def generate_invoice_pdf(my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings):
    pdf, total = build_invoice_pdf(
        my_details, client, invoice_number, items, tax_percent, currency, invoice_date, due_date, settings
    )

    invoices_folder = "invoices_pdf"
    if not os.path.exists(invoices_folder):
        os.makedirs(invoices_folder)

    safe_company = client['Company Name'].replace(' ', '_').replace('/', '_')
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
    base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
    pdf_display = f"""
        <iframe
            src="data:application/pdf;base64,{base64_pdf}"
            width="100%"
            height="820"
            type="application/pdf"
            style="border: 1px solid #ddd; border-radius: 8px; background: white;"
        ></iframe>
    """
    st.markdown(pdf_display, unsafe_allow_html=True)


# --- Settings Page ---
def settings_page():
    page_header(
        "Settings",
        back_label="Back to Main Menu",
        back_page="main",
        help_text="Manage your business details, invoice defaults, branding, and display options."
    )

    business = st.session_state.settings["business_details"]
    defaults = st.session_state.settings["invoice_defaults"]
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

        default_currency = st.selectbox("Default Currency", currency_options, index=currency_options.index(current_currency))
        default_tax = st.number_input("Default Tax Percentage", min_value=0.0, value=float(defaults.get("tax_percentage", 0.0)))
        payment_terms_days = st.number_input("Default Payment Terms (days)", min_value=1, value=int(defaults.get("payment_terms_days", 30)))

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
        footer_text = st.text_area("Invoice Footer Text", branding.get("footer_text", "Thank you for your business!"), height=100)
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
    top_left, top_right = st.columns([3, 2], vertical_alignment="center")

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
        st.button("Generate New Invoice", use_container_width=True, on_click=lambda: st.session_state.update({"page": "create_invoice"}))

    st.markdown("---")
    show_dashboard()


# --- My Clients Page ---
def my_clients_page():
    page_header(
        "My Clients",
        back_label="Back to Main Menu",
        back_page="main",
        help_text="Manage your saved clients and keep your client list organised."
    )

    header_col1, header_col2 = st.columns([1, 4])
    with header_col1:
        if st.button("Add Client", use_container_width=True):
            st.session_state.page = "add_client"
            st.rerun()

    st.markdown("---")

    if not st.session_state.clients:
        st.info("No clients yet.")
        return

    st.subheader("Clients Table")

    df = pd.DataFrame(st.session_state.clients).copy()
    df["Select"] = False

    edited_df = st.data_editor(df, use_container_width=True, num_rows="fixed", hide_index=True)
    selected_rows = edited_df[edited_df["Select"] == True]

    if not selected_rows.empty:
        st.markdown("---")
        st.subheader("Selected Client Actions")
        st.caption(f"{len(selected_rows)} client(s) selected")

        action_col1, action_col2, action_col3 = st.columns([1, 1, 3])

        with action_col1:
            if len(selected_rows) == 1 and st.button("Edit Selected Client", use_container_width=True):
                selected_company = selected_rows.iloc[0]["Company Name"]
                for idx, client in enumerate(st.session_state.clients):
                    if client["Company Name"] == selected_company:
                        st.session_state.edit_client_idx = idx
                        st.session_state.page = "edit_client"
                        st.rerun()

        with action_col2:
            if len(selected_rows) == 1 and st.button("Delete Selected Client", use_container_width=True):
                selected_company = selected_rows.iloc[0]["Company Name"]
                st.session_state.clients = [
                    client for client in st.session_state.clients
                    if client["Company Name"] != selected_company
                ]
                save_json(CLIENTS_FILE, st.session_state.clients)
                st.rerun()


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
        address = st.text_area("Address", height=150)

        if st.button("Save Client", use_container_width=True):
            if company.strip() and contact.strip() and address.strip():
                st.session_state.clients.append({
                    "Company Name": company.strip(),
                    "Contact Person": contact.strip(),
                    "Address": address.strip()
                })
                save_json(CLIENTS_FILE, st.session_state.clients)
                st.success("Client added!")
                st.session_state.page = "my_clients"
                st.rerun()
            else:
                st.warning("Please complete all fields.")


# --- Edit Client Page ---
def edit_client_page():
    idx = st.session_state.edit_client_idx
    client = st.session_state.clients[idx]

    page_header(
        f"Edit Client #{idx+1}",
        back_label="Back to Clients",
        back_page="my_clients",
        help_text="Update the selected client details."
    )

    form_col1, form_col2, form_col3 = st.columns([1.2, 0.1, 1.7])

    with form_col1:
        company = st.text_input("Company Name", client["Company Name"])
        contact = st.text_input("Contact Person", client["Contact Person"])
        address = st.text_area("Address", client["Address"], height=150)

        if st.button("Save Changes", use_container_width=True):
            st.session_state.clients[idx] = {
                "Company Name": company.strip(),
                "Contact Person": contact.strip(),
                "Address": address.strip()
            }
            save_json(CLIENTS_FILE, st.session_state.clients)
            st.success("Client updated!")
            st.session_state.page = "my_clients"
            st.rerun()


# --- Create Invoice Page ---
def create_invoice_page():
    page_header(
        "Generate New Invoice",
        back_label="Back to Main Menu",
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
        default_currency = defaults.get("currency", "AED")
        default_tax = float(defaults.get("tax_percentage", 0.0))
        default_terms = int(defaults.get("payment_terms_days", 30))

        invoice_number = get_next_invoice_number()
        st.text_input("Invoice Number", value=invoice_number, disabled=True)

        date_col1, date_col2 = st.columns(2)
        with date_col1:
            invoice_date = st.date_input("Invoice Date", value=datetime.today())
        with date_col2:
            due_date = st.date_input("Due Date", value=invoice_date + timedelta(days=default_terms))

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
                "Date": invoice_date.strftime('%d/%m/%Y'),
                "Due Date": due_date.strftime('%d/%m/%Y'),
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
                "Date": invoice_date.strftime('%d/%m/%Y'),
                "Due Date": due_date.strftime('%d/%m/%Y'),
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

    df = pd.DataFrame(st.session_state.invoices)

    if 'Total' not in df.columns:
        df['Total'] = 0
    if 'Status' not in df.columns:
        df['Status'] = "Draft"
    if 'Date' not in df.columns:
        df['Date'] = datetime.today().strftime('%d/%m/%Y')

    df['Date_dt'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce')

    today = datetime.today()

    month_mask = (df['Date_dt'].dt.month == today.month) & (df['Date_dt'].dt.year == today.year)
    year_mask = df['Date_dt'].dt.year == today.year

    revenue_month = df.loc[month_mask, 'Total'].sum()
    revenue_year = df.loc[year_mask, 'Total'].sum()
    outstanding_revenue = df.loc[df['Status'].isin(['Sent', 'Overdue']), 'Total'].sum()
    overdue_revenue = df.loc[df['Status'] == 'Overdue', 'Total'].sum()

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Revenue This Month", f"{revenue_month:,.2f}")
    metric_col2.metric("Revenue This Year", f"{revenue_year:,.2f}")
    metric_col3.metric("Outstanding Revenue", f"{outstanding_revenue:,.2f}")
    metric_col4.metric("Overdue Revenue", f"{overdue_revenue:,.2f}")

    st.markdown("---")

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        revenue_by_client = df.groupby('Client')['Total'].sum()
        if not revenue_by_client.empty and revenue_by_client.sum() > 0:
            st.subheader("Revenue by Client")
            fig1, ax1 = plt.subplots()
            ax1.pie(
                revenue_by_client.values,
                labels=revenue_by_client.index,
                autopct='%1.1f%%',
                startangle=90
            )
            ax1.axis('equal')
            st.pyplot(fig1)
        else:
            st.info("No client revenue data yet.")

    with chart_col2:
        revenue_df = df[df['Date_dt'].notna()].copy()
        if not revenue_df.empty:
            revenue_df['Month'] = revenue_df['Date_dt'].dt.to_period('M').astype(str)
            revenue_by_month = revenue_df.groupby('Month')['Total'].sum().sort_index()

            if not revenue_by_month.empty and revenue_by_month.sum() > 0:
                st.subheader("Revenue by Month")
                fig2, ax2 = plt.subplots()
                ax2.plot(revenue_by_month.index, revenue_by_month.values, marker='o')
                ax2.set_xlabel("Month")
                ax2.set_ylabel("Revenue")
                ax2.tick_params(axis='x', rotation=45)
                st.pyplot(fig2)
            else:
                st.info("No monthly revenue data yet.")
        else:
            st.info("No monthly revenue data yet.")


# --- My Invoices Page ---
def my_invoices_page():
    ensure_invoice_fields()

    page_header(
        "My Invoices",
        back_label="Back to Main Menu",
        back_page="main",
        help_text="Browse, filter, update, download, and manage your invoices."
    )

    if not st.session_state.invoices:
        st.info("No invoices yet.")
        return

    df = pd.DataFrame(st.session_state.invoices)
    df['Date_dt'] = pd.to_datetime(df['Date'], format='%d/%m/%Y')
    df['Due_dt'] = pd.to_datetime(df['Due Date'], format='%d/%m/%Y')

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        search = st.text_input("Search Invoice Number")
    with filter_col2:
        clients = ["All"] + sorted(df["Client"].unique().tolist())
        client_filter = st.selectbox("Filter by Client", clients)
    with filter_col3:
        status_filter = st.selectbox("Filter by Status", ["All", "Draft", "Sent", "Paid", "Overdue"])

    filtered_df = df.copy()
    if search:
        filtered_df = filtered_df[filtered_df["Invoice Number"].astype(str).str.contains(search)]
    if client_filter != "All":
        filtered_df = filtered_df[filtered_df['Client'] == client_filter]
    if status_filter != "All":
        filtered_df = filtered_df[filtered_df['Status'] == status_filter]

    st.markdown("---")
    st.subheader("Invoices Table")
    table_df = filtered_df[['Invoice Number', 'Client', 'Date', 'Due Date', 'Status', 'Total']].copy()
    table_df["Select"] = False

    edited_df = st.data_editor(table_df, use_container_width=True, num_rows="fixed", hide_index=True)
    selected_rows = edited_df[edited_df["Select"] == True]

    if not selected_rows.empty:
        st.markdown("---")
        st.subheader("Selected Invoice Actions")
        st.caption(f"{len(selected_rows)} invoice(s) selected")

        row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(4)

        with row1_col1:
            if len(selected_rows) == 1 and st.button("Edit Selected Invoice", use_container_width=True):
                selected_invoice_number = selected_rows.iloc[0]["Invoice Number"]
                for idx, inv in enumerate(st.session_state.invoices):
                    if inv["Invoice Number"] == selected_invoice_number:
                        st.session_state.edit_invoice_idx = idx
                        st.session_state.page = "edit_invoice"
                        st.rerun()

        with row1_col2:
            if st.button("Mark as Draft", use_container_width=True):
                for _, row in selected_rows.iterrows():
                    for inv in st.session_state.invoices:
                        if inv["Invoice Number"] == row["Invoice Number"]:
                            inv["Status"] = "Draft"
                save_json(INVOICES_FILE, st.session_state.invoices)
                st.rerun()

        with row1_col3:
            if st.button("Mark as Sent", use_container_width=True):
                for _, row in selected_rows.iterrows():
                    for inv in st.session_state.invoices:
                        if inv["Invoice Number"] == row["Invoice Number"]:
                            inv["Status"] = "Sent"
                save_json(INVOICES_FILE, st.session_state.invoices)
                st.rerun()

        with row1_col4:
            if st.button("Mark as Paid", use_container_width=True):
                for _, row in selected_rows.iterrows():
                    for inv in st.session_state.invoices:
                        if inv["Invoice Number"] == row["Invoice Number"]:
                            inv["Status"] = "Paid"
                save_json(INVOICES_FILE, st.session_state.invoices)
                st.rerun()

        row2_col1, row2_col2, row2_col3 = st.columns([1, 1, 2])

        with row2_col1:
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

        with row2_col2:
            if st.button("Delete Selected", use_container_width=True):
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

    st.markdown("---")
    footer_col1, footer_col2 = st.columns([1, 3])
    with footer_col1:
        total_revenue = filtered_df["Total"].sum()
        st.metric("Total Revenue (Filtered)", f"{total_revenue:,.2f}")


# --- Navigation ---
if st.session_state.page == "main":
    _ = show_main_menu()
elif st.session_state.page == "my_clients":
    _ = my_clients_page()
elif st.session_state.page == "add_client":
    _ = add_client_page()
elif st.session_state.page == "edit_client":
    _ = edit_client_page()
elif st.session_state.page == "create_invoice":
    _ = create_invoice_page()
elif st.session_state.page == "my_invoices":
    _ = my_invoices_page()
elif st.session_state.page == "edit_invoice":
    _ = edit_invoice_page()
elif st.session_state.page == "settings":
    _ = settings_page()
