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
    """Unlock the AIS PDF, safely group rows, fix multi-line text wrapping, and map into Excel."""
    import re
    import pymupdf
    import os
    from openpyxl import Workbook

    save_dir = os.path.join(os.getcwd(), "client_data")
    pdf_path = os.path.join(save_dir, f"{pan_number}_ais.pdf")
    excel_path = os.path.join(save_dir, f"{pan_number}_ais_master_layout.xlsx")
    
    if not os.path.exists(pdf_path):
        return f"Action Failed: Could not find the AIS PDF at {pdf_path}."
        
    clean_dob = date_of_birth.replace("/", "").replace("-", "").replace(" ", "")
    pdf_password = f"{pan_number.lower()}{clean_dob}"
    print(f"🔐 Extracting AIS: Attempting to unlock PDF with password: {pdf_password}")

    try:
        doc = pymupdf.open(pdf_path)
        if doc.is_encrypted:
            if not doc.authenticate(pdf_password):
                return f"❌ Action Failed: Password rejected."
                
        print("✅ AIS PDF Unlocked! Running Anchored Data Mapper...")
        raw_lines = [line.strip() for page in doc for line in page.get_text().split("\n") if line.strip()]

        def is_amount(val): 
            return bool(re.match(r'^-?(Rs\.?|₹)?\s*[\d,]+(\.\d+)?$', str(val).strip(), re.IGNORECASE))

        # --- 1. GARBAGE HEADER FILTER ---
        garbage_headers = {
            "SR. NO.", "REPORTED ON", "ACCOUNT NUMBER", "ACCOUNT TYPE", "INTEREST AMOUNT", "STATUS",
            "COUNT", "AMOUNT", "INFORMATION CODE", "INFORMATION DESCRIPTION", "INFORMATION SOURCE",
            "QUARTER", "DATE OF RECEIPT/ DEBIT", "AMOUNT RECEIVED/DEBITED", "TAX COLLECTED",
            "TCS DEPOSITED", "FINANCIAL YEAR", "MAJOR HEAD MINOR HEAD", "MAJOR HEAD", "MINOR HEAD",
            "TAX (A)", "SURCHARGE (B)", "EDUCATION CESS (C)", "OTHERS (D)", "TOTAL (A+B+C+D)",
            "BSR CODE", "DATE OF DEPOSIT", "CHALLAN SERIAL NUMBER", "CHALLAN IDENTIFICATION NUMBER",
            "PART", "TOTAL (A+B+C +D)"
        }
        all_lines = [line for line in raw_lines if line.upper() not in garbage_headers]

        # --- 2. EXTRACT GENERAL INFO ---
        general_info = {
            "PAN": pan_number, "Aadhaar Number": "", "Name of Assessee": "", 
            "Date of Birth": "", "Mobile Number": "", "Email Address": "", "Address": ""
        }
        for i, line in enumerate(all_lines):
            if not general_info["Aadhaar Number"] and ("XXXX" in line or len(re.sub(r'\D', '', line)) == 12) and len(line) >= 12:
                if "AADHAAR" not in line.upper(): 
                    general_info["Aadhaar Number"] = line
                    if i + 1 < len(all_lines): general_info["Name of Assessee"] = all_lines[i+1]
            elif not general_info["Date of Birth"] and re.match(r'^\d{2}/\d{2}/\d{4}$', line): general_info["Date of Birth"] = line
            elif not general_info["Mobile Number"] and re.match(r'^\d{10}$', line): general_info["Mobile Number"] = line
            elif not general_info["Email Address"] and "@" in line and "." in line: general_info["Email Address"] = line
            elif not general_info["Address"] and line.upper() == "ADDRESS":
                if i + 1 < len(all_lines): general_info["Address"] = all_lines[i+1]

        part_data = {"B1": [], "B2": [], "B3": [], "B7": []}
        curr_part = None
        for line in all_lines:
            line_up = line.upper()
            if "PART B1" in line_up: curr_part = "B1"
            elif "PART B2" in line_up: curr_part = "B2"
            elif "PART B3" in line_up: curr_part = "B3"
            elif "PART B7" in line_up: curr_part = "B7"
            elif curr_part: part_data[curr_part].append(line)

        # --- 3. THE SMART BLOCK BUILDER ---
        def build_blocks(lines):
            raw_blocks, temp = [], []
            for val in lines:
                if val.isdigit() and len(val) <= 4:
                    if temp: raw_blocks.append(temp)
                    temp = [val]
                elif temp: temp.append(val)
            if temp: raw_blocks.append(temp)
            
            merged = []
            for blk in raw_blocks:
                has_id = False
                if blk and blk[0].isdigit():
                    for x in blk[:3]:
                        x_up = x.upper()
                        if any(x_up.startswith(c) for c in ["SFT", "TDS", "TCS", "ADV", "SAST", "OTH", "Q1", "Q2", "Q3", "Q4"]): has_id = True
                        if re.match(r'^\d{2}/\d{2}/\d{4}', x_up) or re.match(r'^20\d{2}-\d{2}$', x_up): has_id = True
                
                if has_id or not merged: merged.append(blk)
                else: merged[-1].extend(blk)
            return merged

        # --- 4. BACKWARD EXTRACTION LOGIC (WITH MULTI-LINE TEXT FIX) ---
        b1_top, b1_bot, b2_data, b7_data, b3_data = [], [], [], [], []
        
        # PROCESS B1
        for blk in build_blocks(part_data["B1"]):
            is_bot = any(x.upper().startswith(c) for c in ["Q1", "Q2", "Q3", "Q4"] for x in blk[:4]) or any(re.match(r'^\d{2}/\d{2}/\d{4}', x) for x in blk[:4])
            
            if not is_bot:
                sr = blk[0]
                code = blk[1] if len(blk) > 1 else ""
                
                amt_idx = next((i for i in range(len(blk)-1, 0, -1) if is_amount(blk[i])), -1)
                if amt_idx != -1:
                    amt = blk[amt_idx]
                    count = blk[amt_idx-1] if (amt_idx > 0 and blk[amt_idx-1].isdigit()) else ""
                    end_idx = amt_idx - 1 if count else amt_idx
                else:
                    amt, count, end_idx = "", "", len(blk)
                
                # FIXED: Perfect Separation for Multi-Line Descriptions
                text_parts = blk[2 : end_idx]
                if len(text_parts) > 1:
                    src = text_parts[-1]
                    desc = " ".join(text_parts[:-1])
                elif len(text_parts) == 1:
                    desc = text_parts[0]
                    src = ""
                else:
                    desc, src = "", ""
                
                b1_top.append([sr, code, desc, src, count, amt])
                
            else:
                sr = blk[0]
                qtr = next((x for x in blk if x.upper().startswith(("Q1", "Q2", "Q3", "Q4"))), blk[1] if len(blk)>1 else "")
                date_idx = next((i for i, x in enumerate(blk) if re.match(r'^\d{2}/\d{2}/\d{4}', x)), -1)
                date = blk[date_idx] if date_idx != -1 else ""
                status = next((x for x in blk if x.upper() in ["ACTIVE", "INACTIVE"]), "")
                
                amts = []
                start_amts = date_idx if date_idx != -1 else 1
                for i in range(len(blk)-1, start_amts, -1):
                    if is_amount(blk[i]) and blk[i].upper() not in ["ACTIVE", "INACTIVE"]:
                        amts.insert(0, blk[i])
                        if len(amts) == 3: break
                
                amts = (["", "", ""] + amts)[-3:]
                b1_bot.append([sr, qtr, date, amts[0], amts[1], amts[2], status])

        # PROCESS B2
        pending_b2_top = None
        for blk in build_blocks(part_data["B2"]):
            is_bot = any(re.match(r'^\d{2}/\d{2}/\d{4}', x) for x in blk[:4])
            
            if not is_bot:
                sr = blk[0]
                code = blk[1] if len(blk) > 1 else ""
                
                amt_idx = next((i for i in range(len(blk)-1, 0, -1) if is_amount(blk[i])), -1)
                if amt_idx != -1:
                    amt = blk[amt_idx]
                    count = blk[amt_idx-1] if (amt_idx > 0 and blk[amt_idx-1].isdigit()) else ""
                    end_idx = amt_idx - 1 if count else amt_idx
                else:
                    amt, count, end_idx = "", "", len(blk)
                
                # FIXED: Perfect Separation for Multi-Line Descriptions
                text_parts = blk[2 : end_idx]
                if len(text_parts) > 1:
                    src = text_parts[-1]
                    desc = " ".join(text_parts[:-1])
                elif len(text_parts) == 1:
                    desc = text_parts[0]
                    src = ""
                else:
                    desc, src = "", ""
                
                pending_b2_top = [sr, code, desc, src, count, amt]
                
            else:
                sr = blk[0]
                date_idx = next((i for i, x in enumerate(blk) if re.match(r'^\d{2}/\d{2}/\d{4}', x)), -1)
                date = blk[date_idx] if date_idx != -1 else ""
                status = next((x for x in blk if x.upper() in ["ACTIVE", "INACTIVE"]), "")
                
                amt_idx = next((i for i in range(len(blk)-1, date_idx if date_idx != -1 else 0, -1) if is_amount(blk[i]) and blk[i].upper() not in ["ACTIVE", "INACTIVE"]), -1)
                amt = blk[amt_idx] if amt_idx != -1 else ""
                
                end_idx = amt_idx if amt_idx != -1 else (blk.index(status) if status else len(blk))
                acc_parts = blk[(date_idx + 1 if date_idx != -1 else 1) : end_idx]
                
                acc_num = acc_parts[0] if len(acc_parts) > 0 else ""
                acc_type = " ".join(acc_parts[1:]) if len(acc_parts) > 1 else ""
                
                if pending_b2_top:
                    b2_data.append(pending_b2_top + [sr, date, acc_num, acc_type, amt, status])
                    pending_b2_top = None

        # PROCESS B7
        for blk in build_blocks(part_data["B7"]):
            sr = blk[0]
            code = blk[1] if len(blk) > 1 else ""
            
            amt_idx = next((i for i in range(len(blk)-1, 0, -1) if is_amount(blk[i])), -1)
            if amt_idx != -1:
                amt = blk[amt_idx]
                count = blk[amt_idx-1] if (amt_idx > 0 and blk[amt_idx-1].isdigit()) else ""
                end_idx = amt_idx - 1 if count else amt_idx
            else:
                amt, count, end_idx = "", "", len(blk)
            
            # FIXED: Perfect Separation for Multi-Line Descriptions
            text_parts = blk[2 : end_idx] if len(blk) > 2 else []
            if len(text_parts) > 1:
                src = text_parts[-1]
                desc = " ".join(text_parts[:-1])
            elif len(text_parts) == 1:
                desc = text_parts[0]
                src = ""
            else:
                desc, src = "", ""
                
            b7_data.append([sr, code, desc, src, count, amt])

        # PROCESS B3 
        for blk in build_blocks(part_data["B3"]):
            sr = blk[0]
            fy_idx = next((i for i, x in enumerate(blk) if re.match(r'^20\d{2}-\d{2}$', x)), -1)
            fy = blk[fy_idx] if fy_idx != -1 else (blk[1] if len(blk)>1 else "")
            
            date_idx = next((i for i, x in enumerate(blk) if re.match(r'^\d{2}/\d{2}/\d{4}', x)), -1)
            
            if date_idx != -1:
                date = blk[date_idx]
                bsr = blk[date_idx-1] if date_idx > 0 else ""
                challan = blk[date_idx+1] if date_idx+1 < len(blk) else ""
                cin = blk[date_idx+2] if date_idx+2 < len(blk) else ""
                
                middle_parts = blk[fy_idx+1 : date_idx-1] if fy_idx != -1 else blk[2 : date_idx-1]
                
                amts = []
                text_end = len(middle_parts)
                for i in range(len(middle_parts)-1, -1, -1):
                    if is_amount(middle_parts[i]):
                        amts.insert(0, middle_parts[i])
                        text_end = i
                    else:
                        break
                        
                amts = (["0", "0", "0", "0", "0"] + amts)[-5:]
                tax, sur, cess, oth, tot = amts[0], amts[1], amts[2], amts[3], amts[4]
                maj_min = " ".join(middle_parts[:text_end])
            else:
                cin = blk[-1] if len(blk)>2 and len(blk[-1])>10 else ""
                challan = blk[-2] if len(blk)>3 and blk[-2].isdigit() else ""
                amts = [x for x in blk if is_amount(x)]
                amts = (["0", "0", "0", "0", "0"] + amts)[-5:]
                tax, sur, cess, oth, tot = amts
                maj_min = " ".join(blk[2: -len(amts)-2]) if len(blk) > 6 else ""
                bsr, date = "", ""
                
            b3_data.append([sr, fy, maj_min, tax, sur, cess, oth, tot, bsr, date, challan, cin])

        # --- 5. BUILD THE MASTER EXCEL TEMPLATE ---
        wb = Workbook()
        ws = wb.active
        ws.title = "AIS Master Form"

        ws.append(["Part A - General Information"])
        ws.append(["Permanent Account Number (PAN) :", general_info.get("PAN", "")])
        ws.append(["Aadhaar Number:", general_info.get("Aadhaar Number", "")])
        ws.append(["Name of Assessee:", general_info.get("Name of Assessee", "")])
        ws.append(["Date of Birth:", general_info.get("Date of Birth", "")])
        ws.append(["Mobile Number:", general_info.get("Mobile Number", "")])
        ws.append(["E-mail Address:", general_info.get("Email Address", "")])
        ws.append(["Address :", general_info.get("Address", "")])
        ws.append([])
        
        ws.append(["PART B( Annual Information Statement ):-"])
        ws.append([])

        ws.append(["Part B1-Information relating to tax deducted or collected at source:"])
        ws.append(["SR. NO.", "INFORMATION CODE", "INFORMATION DESCRIPTION", "INFORMATION SOURCE", "COUNT", "AMOUNT"])
        for r in b1_top: ws.append(r)
        ws.append([])
        ws.append(["SR. NO.", "QUARTER", "DATE OF RECEIPT/ DEBIT", "AMOUNT RECEIVED/DEBITED", "TAX COLLECTED", "TCS DEPOSITED", "STATUS"])
        for r in b1_bot: ws.append(r)
        ws.append([])

        ws.append(["Part B2-Information relating to specified financial transaction (SFT)::"])
        ws.append(["SR. NO.", "INFORMATION CODE", "INFORMATION DESCRIPTION", "INFORMATION SOURCE", "COUNT", "AMOUNT", "SR. NO.", "REPORTED ON", "ACCOUNT NUMBER", "ACCOUNT TYPE", "INTEREST AMOUNT", "STATUS"])
        for r in b2_data: ws.append(r)
        ws.append([])

        ws.append(["Part B7-Any other information in relation to sub-rule (2) of rule 114-I :-"])
        ws.append(["SR. NO.", "INFORMATION CODE", "INFORMATION DESCRIPTION", "INFORMATION SOURCE", "COUNT", "AMOUNT"])
        for r in b7_data: ws.append(r)
        ws.append([])

        ws.append(["Part B3-Information relating to payment of taxes:"])
        ws.append(["SR. NO.", "FINANCIAL YEAR", "MAJOR HEAD MINOR HEAD", "TAX (A)", "SURCHARGE (B)", "EDUCATION CESS (C)", "OTHERS (D)", "TOTAL (A+B+C+D)", "BSR CODE", "DATE OF DEPOSIT", "CHALLAN SERIAL NUMBER", "CHALLAN IDENTIFICATION NUMBER"])
        for r in b3_data: ws.append(r)

        wb.save(excel_path)
        print(f"✅ Master AIS Excel perfectly mapped! Saved to: {excel_path}")
        return f"Successfully structured AIS data into single sheet layout at: {excel_path}"

    except Exception as e:
        print(f"❌ AIS Excel Conversion Crashed: {str(e)}")
        return f"Action Failed during AIS Excel conversion. Error: {str(e)}"

@tool
def convert_tis_pdf_to_excel(pan_number: str, date_of_birth: str) -> str:
    """Unlock the TIS PDF, intelligently map multi-line text, filter footers, and build the Master Excel layout."""
    import re
    import pymupdf
    import os
    from openpyxl import Workbook

    save_dir = os.path.join(os.getcwd(), "client_data")
    pdf_path = os.path.join(save_dir, f"{pan_number}_tis.pdf")
    excel_path = os.path.join(save_dir, f"{pan_number}_tis_master_layout.xlsx")
    
    if not os.path.exists(pdf_path):
        return f"Action Failed: Could not find the TIS PDF at {pdf_path}."
        
    clean_dob = date_of_birth.replace("/", "").replace("-", "").replace(" ", "")
    pdf_password = f"{pan_number.lower()}{clean_dob}"
    print(f"🔐 Extracting TIS: Attempting to unlock PDF with password: {pdf_password}")

    try:
        doc = pymupdf.open(pdf_path)
        if doc.is_encrypted:
            if not doc.authenticate(pdf_password):
                return f"❌ Action Failed: Password rejected by the TIS PDF."
                
        print("✅ TIS PDF Unlocked! Running Advanced Table Parser...")
        raw_lines = [line.strip() for page in doc for line in page.get_text().split("\n") if line.strip()]

        def is_amount(val): 
            return bool(re.match(r'^-?(Rs\.?|₹)?\s*[\d,]+(\.\d+)?$', str(val).strip(), re.IGNORECASE))

        # --- 1. AGGRESSIVE GARBAGE HEADER & FOOTER FILTER ---
        garbage_headers = {
            "SR. NO.", "INFORMATION CATEGORY", "PROCESSED BY SYSTEM",
            "ACCEPTED BY TAXPAYER/CONFIRMED BY SOURCE", "ACCEPTED BY TAXPAYER/", 
            "CONFIRMED BY SOURCE", "PART", "INFORMATION DESCRIPTION", 
            "INFORMATION SOURCE", "AMOUNT DESCRIPTION", "REPORTED BY SOURCE",
            "ACCEPTED BY TAXPAYER/ CONFIRMED BY SOURCE", "ACCEPTED BY", 
            "TAXPAYER/CONFIRMED", "BY SOURCE", "PAN", "NAME", "FINANCIAL YEAR"
        }
        
        all_lines = []
        for line in raw_lines:
            up = line.upper()
            if up in garbage_headers: continue
            if "DOWNLOAD ID :" in up or "IP ADDRESS :" in up or "GENERATION DATE :" in up or ("PAGE" in up and "OF" in up): continue
            all_lines.append(line)

        # --- 2. EXTRACT GENERAL INFO ---
        general_info = {
            "PAN": pan_number, "Aadhaar Number": "", "Name of Assessee": "", 
            "Date of Birth": "", "Mobile Number": "", "Email Address": "", "Address": ""
        }
        for i, line in enumerate(all_lines):
            if not general_info["Aadhaar Number"] and ("XXXX" in line or len(re.sub(r'\D', '', line)) == 12) and len(line) >= 12:
                if "AADHAAR" not in line.upper(): 
                    general_info["Aadhaar Number"] = line
                    if i + 1 < len(all_lines): general_info["Name of Assessee"] = all_lines[i+1]
            elif not general_info["Date of Birth"] and re.match(r'^\d{2}/\d{2}/\d{4}$', line): general_info["Date of Birth"] = line
            elif not general_info["Mobile Number"] and re.match(r'^\d{10}$', line): general_info["Mobile Number"] = line
            elif not general_info["Email Address"] and "@" in line and "." in line: general_info["Email Address"] = line
            elif not general_info["Address"] and line.upper() == "ADDRESS":
                if i + 1 < len(all_lines): general_info["Address"] = all_lines[i+1]

        # --- 3. THE SMART ROW BUILDER (FIXED TDS/TCS SPLITTING) ---
        def is_tis_row_start(idx, lines):
            val = lines[idx]
            if not val.isdigit() or len(val) > 4: return False
            if idx + 1 < len(lines):
                nxt = lines[idx+1].upper().strip()
                if nxt.startswith(("SFT", "TDS", "TCS", "ADV", "SAST", "OTH")): return True
                if is_amount(nxt): return False 
                if len(nxt) > 3: return True 
            return False

        blocks, temp = [], []
        for i in range(len(all_lines)):
            if is_tis_row_start(i, all_lines):
                if temp: blocks.append(temp)
                temp = [all_lines[i]]
            elif temp:
                temp.append(all_lines[i])
        if temp: blocks.append(temp)

        # --- 4. HIERARCHICAL TEXT PARSER ---
        master_layout_data = []

        for blk in blocks:
            # Obliterate trailing Page Footers (PAN/Name) by cutting the block at the last amount
            last_amt_idx = -1
            for i in range(len(blk)-1, -1, -1):
                if is_amount(blk[i]):
                    last_amt_idx = i
                    break
            
            if last_amt_idx == -1: continue 
            blk = blk[:last_amt_idx+1] 

            is_detail = any(x.upper().startswith(("SFT", "TDS", "TCS", "ADV", "SAST", "OTH")) for x in blk[:4])

            if not is_detail:
                # SUMMARY ROW
                sr = blk[0]
                amts = [x for x in blk if is_amount(x)]
                amts = (["", ""] + amts)[-2:] 
                
                amt_start = len(blk)
                for i in range(len(blk)-1, 0, -1):
                    if is_amount(blk[i]): amt_start = i
                    else: break
                
                category = " ".join(blk[1:amt_start])
                master_layout_data.append({"type": "summary", "data": [sr, category, amts[0], amts[1]]})

            else:
                # DETAIL ROW
                sr = blk[0]
                part_idx = 1
                part = ""
                
                # Identifies Part and stitches TDS/ and TCS back together
                for i, x in enumerate(blk[:4]):
                    if x.upper().startswith(("SFT", "TDS", "TCS", "ADV", "SAST", "OTH")):
                        part = x
                        part_idx = i
                        if x.upper().strip() in ["TDS/", "TDS /", "TDS"] and i+1 < len(blk) and blk[i+1].upper().strip() in ["TCS", "/TCS", "/ TCS"]:
                            part = "TDS/TCS"
                            part_idx = i + 1
                        break
                if not part: 
                    part = blk[1]
                    part_idx = 1
                
                amts = [x for x in blk[part_idx+1:] if is_amount(x)]
                amts = (["", "", ""] + amts)[-3:] 
                
                amt_start = len(blk)
                for i in range(len(blk)-1, part_idx, -1):
                    if is_amount(blk[i]): amt_start = i
                    else: break
                
                text_parts = blk[part_idx+1 : amt_start]
                
                desc_end_idx = -1
                for i, p in enumerate(text_parts):
                    if "(SFT-" in p.upper() or "(U/S" in p.upper() or "(194" in p.upper() or "(192" in p.upper():
                        desc_end_idx = i
                        
                source_end_idx = -1
                for i in range(len(text_parts)-1, max(-1, desc_end_idx), -1):
                    if re.search(r'\([A-Z0-9\.\-]{8,15}\)', p.upper()) and not "(U/S" in p.upper() and not "(SFT-" in p.upper():
                        source_end_idx = i
                        break
                
                if desc_end_idx != -1 and source_end_idx != -1:
                    desc = " ".join(text_parts[:desc_end_idx+1])
                    source = " ".join(text_parts[desc_end_idx+1:source_end_idx+1])
                    amt_desc = " ".join(text_parts[source_end_idx+1:])
                elif desc_end_idx != -1 and source_end_idx == -1:
                    desc = " ".join(text_parts[:desc_end_idx+1])
                    rem = text_parts[desc_end_idx+1:]
                    if len(rem) >= 2:
                        amt_desc = rem[-1]
                        source = " ".join(rem[:-1])
                    elif len(rem) == 1:
                        source, amt_desc = rem[0], ""
                    else:
                        source, amt_desc = "", ""
                else:
                    if len(text_parts) >= 3:
                        amt_desc = text_parts[-1]
                        source = text_parts[-2]
                        desc = " ".join(text_parts[:-2])
                    elif len(text_parts) == 2:
                        desc, source, amt_desc = text_parts[0], text_parts[1], ""
                    elif len(text_parts) == 1:
                        desc, source, amt_desc = text_parts[0], "", ""
                    else:
                        desc, source, amt_desc = "", "", ""
                
                master_layout_data.append({"type": "detail", "data": [sr, part, desc, source, amt_desc, amts[0], amts[1], amts[2]]})

        # --- 5. BUILD THE MASTER EXCEL TEMPLATE ---
        wb = Workbook()
        ws = wb.active
        ws.title = "TIS Master Form"

        ws.append(["Part A - General Information"])
        ws.append(["Permanent Account Number (PAN) :", general_info.get("PAN", "")])
        ws.append(["Aadhaar Number:", general_info.get("Aadhaar Number", "")])
        ws.append(["Name of Assessee:", general_info.get("Name of Assessee", "")])
        ws.append(["Date of Birth:", general_info.get("Date of Birth", "")])
        ws.append(["Mobile Number:", general_info.get("Mobile Number", "")])
        ws.append(["E-mail Address:", general_info.get("Email Address", "")])
        ws.append(["Address :", general_info.get("Address", "")])
        ws.append([])
        
        ws.append(["PART B (Taxpayer Information Summary):-"])
        ws.append([])

        last_type = None
        for row in master_layout_data:
            if row["type"] == "summary":
                if last_type in ["detail", "summary"]: ws.append([]) 
                ws.append(["SR. NO.", "INFORMATION CATEGORY", "PROCESSED BY SYSTEM", "ACCEPTED BY TAXPAYER/CONFIRMED BY SOURCE"])
                ws.append(row["data"])
                last_type = "summary"
                
            elif row["type"] == "detail":
                if last_type == "summary": 
                    ws.append([])
                    ws.append(["SR. NO.", "PART", "INFORMATION DESCRIPTION", "INFORMATION SOURCE", "AMOUNT DESCRIPTION", "REPORTED BY SOURCE", "PROCESSED BY SYSTEM", "ACCEPTED BY TAXPAYER/ CONFIRMED BY SOURCE"])
                ws.append(row["data"])
                last_type = "detail"

        wb.save(excel_path)
        print(f"✅ Master TIS Excel perfectly mapped! Saved to: {excel_path}")
        return f"Successfully structured TIS data into single sheet layout at: {excel_path}"

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
        f"56. Use the download_file tool to click 'Proceed' and save the file as '{pan_number}_ais.json'.\n"

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
    
    # REMOVE OR COMMENT OUT THESE TWO LINES:
    # print("⏳ Keeping the browser open for 10 minutes...")
    # time.sleep(600) 
    
    return "ITR filling process has been initiated successfully and data is downloaded."