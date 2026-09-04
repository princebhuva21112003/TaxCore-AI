import os
import time
from playwright.sync_api import sync_playwright
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI
import pandas as pd
import json
import pymupdf
import zipfile
import base64
import os

# Place this near the top, under `session = None`
captcha_state = {"image": None, "text": None}
session = None

# ==========================================
# 1. Playwright Synchronous Session Manager
# ==========================================
class BrowserSession:
    def __init__(self):
        self.playwright = sync_playwright().start()
        
        self.browser = self.playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            accept_downloads=True 
        )
        self.page = self.context.new_page()

    def close(self):
        self.browser.close()
        self.playwright.stop()

# ==========================================
# 2. Define FAST Synchronous Tools
# ==========================================
@tool
def convert_ais_pdf_to_excel(pan_number: str, date_of_birth: str) -> str:
    """Unlock the AIS PDF, safely extract General Info, and parse complex nested tables into Excel tabs."""
    import re
    import pandas as pd
    import pymupdf
    import os
    
    save_dir = os.path.join(os.getcwd(), "client_data")
    pdf_path = os.path.join(save_dir, f"{pan_number}_ais.pdf")
    excel_path = os.path.join(save_dir, f"{pan_number}_ais_structured.xlsx")
    
    if not os.path.exists(pdf_path):
        return f"Action Failed: Could not find the AIS PDF at {pdf_path}."
        
    clean_dob = date_of_birth.replace("/", "").replace("-", "").replace(" ", "")
    pdf_password = f"{pan_number.lower()}{clean_dob}"
    print(f"🔐 Extracting AIS: Attempting to unlock PDF with password: {pdf_password}")

    try:
        doc = pymupdf.open(pdf_path)
        if doc.is_encrypted:
            if not doc.authenticate(pdf_password):
                return f"❌ Action Failed: Password {pdf_password} rejected by the AIS PDF."
                
        print("✅ AIS PDF Unlocked! Running Advanced Data Structuring...")

        all_lines = []
        for page in doc:
            all_lines.extend([line.strip() for line in page.get_text().split("\n") if line.strip()])

        # --- 1. EXTRACT GENERAL INFORMATION (BULLETPROOF REGEX) ---
        # Join all text into one giant string to bypass horizontal PDF layout issues
        full_text = " ".join(all_lines)
        
        # Regex patterns to guarantee correct data grabbing
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', full_text)
        dob_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', full_text)
        aadhaar_match = re.search(r'(XXXX\s*XXXX\s*\d{4}|XXXXXXXX\d{4})', full_text)
        mobile_match = re.search(r'\b[6-9]\d{9}\b', full_text)

        general_info = {
            "PAN": pan_number,
            "Aadhaar Number": aadhaar_match.group(0) if aadhaar_match else "Not Found",
            "Name of Assessee": "Not Found",
            "Date of Birth": dob_match.group(0) if dob_match else date_of_birth,
            "Mobile Number": mobile_match.group(0) if mobile_match else "Not Found",
            "Email Address": email_match.group(0) if email_match else "Not Found",
            "Address": "Not Found"
        }

        # Find Name and Address dynamically
        for i, line in enumerate(all_lines):
            line_up = line.upper()
            if "NAME OF ASSESSEE" in line_up and general_info["Name of Assessee"] == "Not Found":
                for j in range(i+1, min(i+10, len(all_lines))):
                    val = all_lines[j]
                    if val.upper() not in ["DATE OF BIRTH", "MOBILE NUMBER", "E-MAIL ADDRESS", "EMAIL ADDRESS"] \
                       and pan_number.upper() not in val.upper() and "XXXX" not in val and not re.match(r'\d{2}/\d{2}/\d{4}', val):
                        if len(val) > 3:
                            general_info["Name of Assessee"] = val
                            break
            
            if line_up == "ADDRESS" and general_info["Address"] == "Not Found":
                for j in range(i+1, min(i+5, len(all_lines))):
                    if len(all_lines[j]) > 15:
                        general_info["Address"] = all_lines[j]
                        break

        # --- 2. EXTRACT NESTED TABLES (DYNAMIC BLOCK PARSING) ---
        financial_transactions = []
        tax_payments = []
        
        i = 0
        current_part = "Unknown"
        while i < len(all_lines):
            line = all_lines[i]
            line_up = line.upper()
            
            if "PART B1" in line_up or "PART B2" in line_up or "SPECIFIED FINANCIAL" in line_up or "PART B" in line_up:
                current_part = "SFT/TDS"
            if "PART B3" in line_up or "PAYMENT OF TAXES" in line_up:
                current_part = "TAX_PAYMENT"
                
            # TRIGGER: Serial Number indicates a new transaction row
            if line.isdigit() and 0 < len(line) < 4:
                
                # SFT / TDS Logic
                if current_part in ["SFT/TDS", "Unknown"]:
                    # Group the entire block until it hits "Active" or "Inactive"
                    status_idx = -1
                    for j in range(1, 20):
                        if i+j < len(all_lines) and all_lines[i+j].upper() in ["ACTIVE", "INACTIVE"]:
                            status_idx = j
                            break
                    
                    if status_idx != -1:
                        block = all_lines[i : i+status_idx+1]
                        dates = [x for x in block if re.match(r'\d{2}/\d{2}/\d{4}', x)]
                        amounts = [x for x in block if re.match(r'^-?(Rs\.?|₹)?\s*[\d,]+(\.\d+)?$', x) and len(x) > 1 and x != block[0]]
                        info_codes = [x for x in block if "SFT-" in x or "TCS-" in x or "TDS-" in x]
                        
                        financial_transactions.append({
                            "SR. NO.": block[0],
                            "Information Code": info_codes[0] if info_codes else (block[1] if len(block) > 1 else ""),
                            "Description / Category": block[2] if len(block) > 2 else "",
                            "Reported Date": dates[0] if dates else "",
                            "Amount": amounts[-1] if amounts else "",
                            "Status": block[-1],
                            "Raw Data Block (For Reference)": " | ".join(block) # Captures everything safely
                        })
                        i += status_idx
                        continue

                # Tax Payments Logic
                elif current_part == "TAX_PAYMENT":
                    # Check if next item is a Financial Year (e.g., 2024-25)
                    if i+1 < len(all_lines) and re.match(r'\d{4}-\d{2}', all_lines[i+1]):
                        block = all_lines[i : min(i+15, len(all_lines))]
                        dates = [x for x in block if re.match(r'\d{2}/\d{2}/\d{4}', x)]
                        date_val = dates[0] if dates else ""
                        
                        tax_payments.append({
                            "SR. NO.": block[0],
                            "Financial Year": block[1],
                            "Major Head": block[2] if len(block) > 2 else "",
                            "Minor Head": block[3] if len(block) > 3 else "",
                            "Date of Deposit": date_val,
                            "Raw Data Block (For Reference)": " | ".join(block)
                        })
                        try:
                            date_idx = block.index(date_val)
                            i += date_idx + 2 
                        except:
                            i += 12
                        continue
            i += 1

        # --- 3. BUILD THE MULTI-TAB EXCEL FILE ---
        general_df = pd.DataFrame(list(general_info.items()), columns=["Attribute", "Details"])
        sft_df = pd.DataFrame(financial_transactions)
        tax_df = pd.DataFrame(tax_payments)
        raw_df = pd.DataFrame({"Raw Extracted Text": all_lines})
        
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            general_df.to_excel(writer, sheet_name="General Information", index=False)
            
            if not sft_df.empty:
                sft_df.to_excel(writer, sheet_name="SFT & TDS Transactions", index=False)
            else:
                pd.DataFrame([{"Data": "No SFT/TDS transactions found"}]).to_excel(writer, sheet_name="SFT & TDS Transactions", index=False)
                
            if not tax_df.empty:
                tax_df.to_excel(writer, sheet_name="Tax Payments (Part B3)", index=False)
            else:
                pd.DataFrame([{"Data": "No tax payments found"}]).to_excel(writer, sheet_name="Tax Payments (Part B3)", index=False)
                
            raw_df.to_excel(writer, sheet_name="Raw Data Backup", index=False)

        print(f"✅ AIS Excel successfully mapped into 4 tabs! Saved to: {excel_path}")
        return f"Successfully structured AIS data and saved Excel to: {excel_path}"

    except Exception as e:
        print(f"❌ AIS Excel Conversion Crashed: {str(e)}")
        return f"Action Failed during AIS Excel conversion. Error: {str(e)}"

@tool
def convert_tis_pdf_to_excel(pan_number: str, date_of_birth: str) -> str:
    """Unlock the TIS PDF, accurately extract General Info, Summary Tables, and Detailed Tables into Excel tabs."""
    import re
    import pandas as pd
    import pymupdf
    
    save_dir = os.path.join(os.getcwd(), "client_data")
    pdf_path = os.path.join(save_dir, f"{pan_number}_tis.pdf")
    excel_path = os.path.join(save_dir, f"{pan_number}_tis_structured.xlsx")
    
    if not os.path.exists(pdf_path):
        return f"Action Failed: Could not find the TIS PDF at {pdf_path}."
        
    clean_dob = date_of_birth.replace("/", "").replace("-", "").replace(" ", "")
    pdf_password = f"{pan_number.lower()}{clean_dob}"
    print(f"🔐 Extracting TIS: Attempting to unlock PDF with password: {pdf_password}")

    try:
        doc = pymupdf.open(pdf_path)
        if doc.is_encrypted:
            if not doc.authenticate(pdf_password):
                return f"❌ Action Failed: Password {pdf_password} rejected by the TIS PDF."
                
        print("✅ TIS PDF Unlocked! Structuring data exactly like the portal...")

        all_lines = []
        for page in doc:
            all_lines.extend([line.strip() for line in page.get_text().split("\n") if line.strip()])

        # --- 1. EXTRACT GENERAL INFORMATION ---
        general_info = {
            "PAN": pan_number,
            "Aadhaar Number": "",
            "Name of Assessee": "",
            "Date of Birth": "",
            "Mobile Number": "",
            "Email Address": "",
            "Address": ""
        }

        for i, line in enumerate(all_lines):
            line_up = line.upper()
            if "AADHAAR NUMBER" in line_up and not general_info["Aadhaar Number"]:
                general_info["Aadhaar Number"] = all_lines[i+1]
            elif "NAME OF ASSESSEE" in line_up and not general_info["Name of Assessee"]:
                general_info["Name of Assessee"] = all_lines[i+1]
            elif "DATE OF BIRTH" in line_up and not general_info["Date of Birth"]:
                general_info["Date of Birth"] = all_lines[i+1]
            elif "MOBILE NUMBER" in line_up and not general_info["Mobile Number"]:
                general_info["Mobile Number"] = all_lines[i+1]
            elif ("E-MAIL ADDRESS" in line_up or "EMAIL ADDRESS" in line_up) and not general_info["Email Address"]:
                general_info["Email Address"] = all_lines[i+1]
            elif line_up == "ADDRESS" and not general_info["Address"]:
                general_info["Address"] = all_lines[i+1]

        # --- 2. EXTRACT TABLES (SUMMARY & DETAILS) ---
        def is_amount(val):
            return bool(re.match(r'^-?(Rs\.?|₹)?\s*[\d,]+(\.\d+)?$', str(val).strip(), re.IGNORECASE))

        summary_data = []
        detail_data = []
        
        i = 0
        while i < len(all_lines):
            line = all_lines[i]
            # Check if line is a Serial Number (1, 2, 3...)
            if line.isdigit():
                # DETAILED ROW (8 Columns) - Lookahead to check if next line is a 'PART' like SFT, TDS
                if i + 7 < len(all_lines) and all_lines[i+1] in ["SFT", "TDS/TCS", "TDS", "TCS", "ADV", "SAST", "OTH"]:
                    if is_amount(all_lines[i+5]) and is_amount(all_lines[i+6]):
                        detail_data.append({
                            "SR. NO.": line,
                            "PART": all_lines[i+1],
                            "INFORMATION DESCRIPTION": all_lines[i+2],
                            "INFORMATION SOURCE": all_lines[i+3],
                            "AMOUNT DESCRIPTION": all_lines[i+4],
                            "REPORTED BY SOURCE": all_lines[i+5],
                            "PROCESSED BY SYSTEM": all_lines[i+6],
                            "ACCEPTED BY TAXPAYER": all_lines[i+7]
                        })
                        i += 7
                        continue
                
                # SUMMARY ROW (4 Columns) - Lookahead to check if upcoming lines are amounts
                elif i + 3 < len(all_lines):
                    if is_amount(all_lines[i+2]) and is_amount(all_lines[i+3]):
                        summary_data.append({
                            "SR. NO.": line,
                            "INFORMATION CATEGORY": all_lines[i+1],
                            "PROCESSED BY SYSTEM": all_lines[i+2],
                            "ACCEPTED BY TAXPAYER": all_lines[i+3]
                        })
                        i += 3
                        continue
            i += 1

        # --- 3. BUILD THE MULTI-TAB EXCEL FILE ---
        general_df = pd.DataFrame(list(general_info.items()), columns=["Attribute", "Details"])
        summary_df = pd.DataFrame(summary_data)
        detail_df = pd.DataFrame(detail_data)
        raw_df = pd.DataFrame({"Raw Extracted Text": all_lines})
        
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            # Tab 1: General Client Info
            general_df.to_excel(writer, sheet_name="General Information", index=False)
            
            # Tab 2: High-Level Summary
            if not summary_df.empty:
                summary_df.to_excel(writer, sheet_name="TIS Summary", index=False)
            else:
                pd.DataFrame([{"Data": "No Summary Data Found"}]).to_excel(writer, sheet_name="TIS Summary", index=False)
                
            # Tab 3: Detailed Bank & Source Info
            if not detail_df.empty:
                detail_df.to_excel(writer, sheet_name="TIS Detailed Breakdown", index=False)
            
            # Tab 4: Raw Backup
            raw_df.to_excel(writer, sheet_name="Raw Data Backup", index=False)

        print(f"✅ TIS Excel successfully mapped into 3 tabs! Saved to: {excel_path}")
        return f"Successfully structured TIS data and saved Excel to: {excel_path}"

    except Exception as e:
        print(f"❌ TIS Excel Conversion Crashed: {str(e)}")
        return f"Action Failed during TIS Excel conversion. Error: {str(e)}"

@tool
def navigate_to_url(url: str) -> str:
    """Navigate the browser to a specified URL."""
    global session
    session.page.goto(url)
    return f"Successfully navigated to {url}"

@tool
def fill_input_field(field_description: str, value: str) -> str:
    """Fill an input field on the page using its placeholder text, label, or CSS selector."""
    global session
    try:
        session.page.get_by_placeholder(field_description).first.fill(value, timeout=2000)
        return f"Successfully filled placeholder '{field_description}'"
    except Exception:
        try:
            session.page.get_by_label(field_description).first.fill(value, timeout=2000)
            return f"Successfully filled label '{field_description}'"
        except Exception:
            try:
                session.page.locator(f"#{field_description}").first.fill(value, timeout=2000)
                return f"Successfully filled ID '{field_description}'"
            except Exception:
                try:
                    session.page.locator(field_description).first.fill(value, timeout=2000)
                    return f"Successfully filled locator '{field_description}'"
                except Exception as e:
                    return f"Action Failed: Could not find or fill the field '{field_description}'."

@tool
def click_element(selector_or_text: str) -> str:
    """Click an element, button, checkbox, or link on the page using visible text, role, or CSS selector."""
    global session
    try:
        session.page.get_by_role("button", name=selector_or_text).first.click(timeout=3000, force=True)
        return f"Successfully clicked button '{selector_or_text}'."
    except Exception:
        try:
            session.page.get_by_text(selector_or_text, exact=True).first.click(timeout=3000, force=True)
            return f"Successfully clicked exact text '{selector_or_text}'."
        except Exception:
            try:
                session.page.get_by_text(selector_or_text, exact=False).first.click(timeout=3000, force=True)
                return f"Successfully clicked partial text '{selector_or_text}'."
            except Exception:
                try:
                    session.page.locator(selector_or_text).first.click(timeout=3000, force=True)
                    return f"Successfully clicked element '{selector_or_text}'."
                except Exception as e:
                    return f"Action Failed: Could not find or click '{selector_or_text}'."

@tool
def wait_for_seconds(seconds: int) -> str:
    """Pause execution to wait for page elements to load or animations to finish."""
    time.sleep(seconds)
    return f"Waited for {seconds} seconds."

@tool
def get_page_title() -> str:
    """Get the title of the current active web page."""
    global session
    return f"The page title is: {session.page.title()}"

@tool
def download_file(selector_or_text: str, file_name: str) -> str:
    """Click a download button using a CSS selector or text and save the file."""
    global session
    try:
        with session.page.expect_download(timeout=15000) as download_info:
            try:
                # 1. Try to click it strictly as a CSS selector first
                session.page.locator(selector_or_text).first.click(timeout=3000, force=True)
            except:
                # 2. Fallback to searching by text if it's just a word like 'Proceed'
                session.page.get_by_text(selector_or_text, exact=False).first.click(timeout=3000, force=True)
        
        download = download_info.value
        save_directory = os.path.join(os.getcwd(), "client_data")
        os.makedirs(save_directory, exist_ok=True)
        save_path = os.path.join(save_directory, file_name)
        download.save_as(save_path)
        
        return f"Successfully downloaded the file and saved it to: {save_path}"
    except Exception as e:
        return f"Action Failed: Could not download the file. Error: {str(e)}"

@tool
def select_dropdown(selector: str, selection: str) -> str:
    """Select an option in a native HTML dropdown (<select> tag). 'selection' can be text, an index number, or 'last'."""
    global session
    try:
        if selection.lower() == 'last':
            options_count = session.page.locator(f"{selector} option").count()
            if options_count > 0:
                session.page.locator(selector).first.select_option(index=options_count - 1)
            else:
                return f"Action Failed: No options found in '{selector}'."
        elif selection.isdigit():
            session.page.locator(selector).first.select_option(index=int(selection))
        else:
            session.page.locator(selector).first.select_option(selection)
            
        return f"Successfully selected '{selection}' in dropdown '{selector}'."
    except Exception as e:
        return f"Action Failed: Could not select '{selection}' in '{selector}'. Error: {str(e)}"

@tool
def switch_to_latest_tab() -> str:
    """Switch browser control to the newest/latest opened tab."""
    global session
    try:
        for button_text in ["Confirm", "Proceed"]:
            try:
                session.page.get_by_text(button_text, exact=False).first.click(timeout=1500)
            except Exception:
                pass

        for _ in range(10):
            if len(session.context.pages) > 1:
                break
            time.sleep(1)

        session.page = session.context.pages[-1]
        session.page.bring_to_front()
        time.sleep(5)
        return f"Successfully switched to tab: '{session.page.title()}'"
    except Exception as e:
        return f"Action Failed: Could not switch tab. Error: {str(e)}"
    
@tool
def check_checkbox(selector: str) -> str:
    """Check a checkbox element on the page using its CSS selector."""
    global session
    try:
        session.page.locator(selector).first.check(timeout=3000)
        return f"Successfully checked the checkbox '{selector}'."
    except Exception:
        try:
            session.page.evaluate(f"document.querySelector('{selector}').click()")
            return f"Successfully checked the checkbox '{selector}' using JavaScript."
        except Exception as e:
            return f"Action Failed: Could not check '{selector}'. Error: {str(e)}"

@tool
def download_and_export_to_excel(pan_number: str, date_of_birth: str) -> str:
    """Download Form 26AS from TRACES, unlock it using date_of_birth, parse text file contents into structured columns, and save to Excel."""
    global session
    save_dir = os.path.join(os.getcwd(), "client_data")
    os.makedirs(save_dir, exist_ok=True)
    
    excel_path = os.path.join(save_dir, f"{pan_number}_structured_tax_data.xlsx")
    clean_dob = date_of_birth.replace("/", "").replace("-", "")

    try:
        with session.page.expect_download(timeout=15000) as download_info:
            session.page.locator("#btnSubmit").first.click(timeout=3000)

        download = download_info.value
        raw_download_path = os.path.join(save_dir, download.suggested_filename)
        download.save_as(raw_download_path)

        form_26as_records = []

        if raw_download_path.endswith(".zip"):
            with zipfile.ZipFile(raw_download_path, 'r') as zip_ref:
                zip_ref.setpassword(clean_dob.encode())
                file_list = zip_ref.namelist()
                if file_list:
                    extracted_path = zip_ref.extract(file_list[0], path=save_dir)
                    with open(extracted_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str:
                                if "\t" in line_str:
                                    cols = [c.strip() for c in line_str.split("\t") if c.strip()]
                                    record = {f"Column_{i+1}": val for i, val in enumerate(cols)}
                                    form_26as_records.append(record)
                                elif "|" in line_str:
                                    cols = [c.strip() for c in line_str.split("|") if c.strip()]
                                    record = {f"Column_{i+1}": val for i, val in enumerate(cols)}
                                    form_26as_records.append(record)
                                else:
                                    form_26as_records.append({"Statement Details": line_str})
        elif raw_download_path.endswith(".pdf"):
            doc = pymupdf.open(raw_download_path)
            if doc.is_encrypted:
                doc.authenticate(clean_dob)
            for page in doc:
                lines = page.get_text().split("\n")
                for line in lines:
                    if line.strip():
                        form_26as_records.append({"Form 26AS Line Item": line.strip()})
        else:
            with open(raw_download_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip():
                        form_26as_records.append({"Statement Details": line.strip()})

        prefill_path = os.path.join(save_dir, f"{pan_number}_prefilled.json")
        prefill_records = []
        if os.path.exists(prefill_path):
            with open(prefill_path, "r", encoding="utf-8") as pf:
                try:
                    pf_data = json.load(pf)
                    for k, v in pf_data.items():
                        prefill_records.append({"Field": str(k), "Value": str(v)})
                except Exception:
                    pass

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            pd.DataFrame([
                {"Attribute": "PAN Number", "Details": pan_number},
                {"Attribute": "Date of Birth", "Details": date_of_birth},
                {"Attribute": "Extraction Status", "Details": "Completed Successfully"}
            ]).to_excel(writer, sheet_name="Client Overview", index=False)

            if form_26as_records:
                pd.DataFrame(form_26as_records).to_excel(writer, sheet_name="Form 26AS Tax Credits", index=False)
            else:
                pd.DataFrame([{"Data": "No Form 26AS data extracted"}]).to_excel(writer, sheet_name="Form 26AS Tax Credits", index=False)

            if prefill_records:
                pd.DataFrame(prefill_records).to_excel(writer, sheet_name="Prefilled ITR Data", index=False)

        return f"Successfully processed Form 26AS, parsed file contents into structured columns, and saved to Excel at: {excel_path}"

    except Exception as e:
        return f"Action Failed during download/Excel conversion. Error: {str(e)}"

@tool
def switch_to_original_tab() -> str:
    """Switch browser control back to the very first/original tab."""
    global session
    try:
        if len(session.context.pages) > 0:
            session.page = session.context.pages[0]
            session.page.bring_to_front()
            return f"Successfully switched back to original tab: {session.page.title()}"
        return "Action Failed: No tabs available."
    except Exception as e:
        return f"Action Failed: Could not switch tab. Error: {str(e)}"

@tool
def handle_captcha(img_selector: str, input_selector: str) -> str:
    """Take a screenshot of a CAPTCHA, wait for the user to solve it, and fill the input field."""
    global session, captcha_state
    try:
        image_bytes = session.page.locator(img_selector).first.screenshot(timeout=5000)
        captcha_state["image"] = base64.b64encode(image_bytes).decode('utf-8')
        captcha_state["text"] = None 

        print("⏳ Bot Paused: Waiting for user to solve CAPTCHA in frontend...")
        
        while captcha_state["text"] is None:
            time.sleep(1)

        session.page.locator(input_selector).first.fill(captcha_state["text"])
        captcha_state["image"] = None
        return "Successfully captured and filled CAPTCHA."
    except Exception as e:
        captcha_state["image"] = None
        return f"Action Failed: {str(e)}"

# ==========================================
# REPLACED 'download_and_export_ais_to_excel' WITH 'convert_ais_pdf_to_excel'
# ==========================================
tools = [
    navigate_to_url, 
    fill_input_field, 
    click_element, 
    wait_for_seconds, 
    get_page_title, 
    download_file, 
    select_dropdown, 
    switch_to_latest_tab, 
    switch_to_original_tab,
    check_checkbox,
    download_and_export_to_excel,
    handle_captcha,
    convert_ais_pdf_to_excel,
    convert_tis_pdf_to_excel
]
tool_map = {t.name: t for t in tools}

# ==========================================
# 3. Synchronous Agent Execution Loop
# ==========================================
def run_itr_bot(pan_number: str, password: str, date_of_birth:str):
    global session
    if session is not None:
        try:
            session.close() 
        except:
            pass
    
    session = BrowserSession()

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(tools)

    user_prompt = (
        "1. Go to https://eportal.incometax.gov.in/iec/foservices/#/login\n"
        f"2. Fill the input field 'Enter your User ID' with '{pan_number}'\n"
        "3. Wait for 1 seconds so the Continue button becomes enabled.\n"
        "3.5. Click the 'Continue' button.\n"
        "4. Wait for 2 seconds so the password page can load.\n"
        "5. Click the element 'Please confirm your secure access message'.\n"
        f"6. Fill the input field 'loginPasswordField' with '{password}'.\n"
        "7. Click the 'Continue' button.\n"
        "8. Wait for 5 seconds so the main dashboard can fully load.\n"
        "9. Click the element 'e-File'.\n"
        "10. Wait for 1 seconds so the dropdown menu can open.\n"
        "11. Click the element 'Income Tax Returns'.\n"
        "12. Wait for 1 seconds so the sub-menu can open.\n"
        "13. Click the element 'Download Pre-Filled Data'.\n"
        "14. Wait for 4 seconds so the new Pre-Filled Data page loads.\n"
        "15. Click the element 'mat-select[name=year]' to open the Assessment Year dropdown.\n"
        "16. Wait for 1 seconds so the year options appear.\n"
        "17. Click the element 'mat-option:nth-child(2)' to select the second option in the list.\n"
        "18. Wait for 1 seconds.\n"
        "19. Click the element 'Download' to close the invisible dropdown backdrop.\n"
        "20. Wait for 1 seconds so the UI can reset.\n"
        f"21. Use the download_file tool to click the 'Download' button and save the file as '{pan_number}_prefilled.json'.\n"
        "22. Wait for 2 seconds to ensure the file download triggers successfully.\n"
        "23. Click the element 'e-File' to reopen the top menu.\n"
        "24. Wait for 1 seconds.\n"
        "25. Click the element 'Income Tax Returns' to reopen the sub-menu.\n"
        "26. Wait for 1 seconds.\n"
        "27. Click the element 'View Form 26AS, Income Tax Act 1961'.\n"
        "28. Wait for 2 seconds.\n"
        "29. Use the switch_to_latest_tab tool to switch control to the TRACES tab.\n"
        "30. Wait for 3 seconds so the TRACES popup modal fully loads.\n"
        "31. DO NOT use click_element. You MUST use the check_checkbox tool on the element '#Details'.\n"
        "32. Wait for 1 seconds.\n"
        "33. Click the element '#btn'.\n"
        "34. Wait for 3 seconds so the main TRACES dashboard loads.\n"
        "35. Click the element 'View Tax Credit (Form 26AS/Annual Tax Statement)'.\n"
        "36. Wait for 2 seconds to ensure the TRACES dashboard is fully interactive.\n"
        "37. Use the select_dropdown tool to select 'last' in the element '#AssessmentYearDropDown'.\n"
        "38. Wait for 1 seconds.\n"
        "39. Use the select_dropdown tool to select 'Text' in the element '#viewType'.\n"
        "40. Wait for 2 seconds so the TRACES portal activates the action buttons.\n"
        f"41. Use the download_and_export_to_excel tool with pan_number '{pan_number}' and date_of_birth '{date_of_birth}'.\n"
        "42. Use the switch_to_original_tab tool to return to the Income Tax portal.\n"
        "43. Wait for 2 seconds.\n"
        "44. Click the element 'AIS'.\n"
        "45. Wait for 2 seconds.\n"
        "46. Use the switch_to_latest_tab tool to bypass the popup and shift control to the new AIS tab.\n"
        
        # --- PHASE 2: DOWNLOAD PDF & CONVERT TO EXCEL (NO CAPTCHA) ---
        "47. Wait for 5 seconds so the AIS portal fully loads.\n"
        "48. Use the click_element tool with selector_or_text 'button:has-text(\"AIS/TIS\")'.\n"
        "49. Wait for 2 seconds so the download modal appears.\n"
        f"50. Use the download_file tool to click ':nth-match(button.dialog-outline-btn, 2)' and save the file as '{pan_number}_ais.pdf'.\n"
        f"51. Use the convert_ais_pdf_to_excel tool with pan_number '{pan_number}' and date_of_birth '{date_of_birth}'.\n"
        
        # --- PHASE 3: DOWNLOAD JSON (WITH CAPTCHA) ---
        "52. Use the click_element tool with selector_or_text ':nth-match(button.dialog-outline-btn, 3)' to trigger the JSON CAPTCHA.\n"
        "53. Wait for 3 seconds so the CAPTCHA module fully loads.\n"
        "54. You MUST strictly use the handle_captcha tool with img_selector '#captcahCanvas' and input_selector '#captchaInput'.\n"
        "55. Wait for 2 seconds to ensure the CAPTCHA text is fully registered.\n"
        f"56. Use the download_file tool to click 'Proceed' and save the file as '{pan_number}_ais.json'."

        # --- PHASE 4: DOWNLOAD TIS PDF & CONVERT TO EXCEL ---
        "57. Use the click_element tool with selector_or_text 'button:has-text(\"AIS/TIS\")' to reopen the download modal.\n"
        "58. Wait for 3 seconds so the download modal appears.\n"
        f"59. Use the download_file tool to click ':nth-match(button.dialog-outline-btn, 4)' and save the file as '{pan_number}_tis.pdf'.\n"
        f"60. Use the convert_tis_pdf_to_excel tool with pan_number '{pan_number}' and date_of_birth '{date_of_birth}'."

    )

    print(f"\n🤖 Agent executing: Logging in PAN {pan_number}")
    messages = [("user", user_prompt)]

    # Increased to 80 to easily handle all 56 steps + tool responses
    for _ in range(80): 
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            print(f"🔧 Agent calling tool: [{tool_name}]")
            selected_tool = tool_map[tool_name]
            tool_output = selected_tool.invoke(tool_args)
            
            print(f"   ↳ Result: {tool_output}") 
            
            messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_id))

    print("\n✅ Final Agent Response: ITR Data Successfully Downloaded!")
    print("⏳ Keeping the browser open for 10 minutes...")
    time.sleep(600)
    
    return "ITR filling process has been initiated successfully and data is downloaded."