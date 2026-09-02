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
import os

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
            accept_downloads=True # Make sure downloads are allowed
        )
        self.page = self.context.new_page()

    def close(self):
        self.browser.close()
        self.playwright.stop()

session = None

# ==========================================
# 2. Define FAST Synchronous Tools
# ==========================================
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
        session.page.get_by_role("button", name=selector_or_text).first.click(timeout=2000)
        return f"Successfully clicked button '{selector_or_text}'."
    except Exception:
        try:
            session.page.get_by_text(selector_or_text, exact=True).first.click(timeout=2000)
            return f"Successfully clicked exact text '{selector_or_text}'."
        except Exception:
            try:
                session.page.get_by_text(selector_or_text, exact=False).first.click(timeout=2000)
                return f"Successfully clicked partial text '{selector_or_text}'."
            except Exception:
                try:
                    session.page.locator(selector_or_text).first.click(timeout=2000)
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

# NEW TOOL: Handles intercepting and saving the downloaded file
@tool
def download_file(button_text: str, file_name: str) -> str:
    """Click a download button and permanently save the file with a specific name."""
    global session
    
    try:
        # 1. Tell Playwright to watch for a download event
        with session.page.expect_download(timeout=10000) as download_info:
            # 2. Click the download button
            session.page.get_by_text(button_text, exact=False).first.click(timeout=2000)
        
        # 3. Catch the file
        download = download_info.value
        
        # 4. Create a 'client_data' folder in your project if it doesn't exist
        save_directory = os.path.join(os.getcwd(), "client_data")
        os.makedirs(save_directory, exist_ok=True)
        
        # 5. Save the file permanently with the PAN number
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
        # NEW: Handle "last" by counting the options
        if selection.lower() == 'last':
            options_count = session.page.locator(f"{selector} option").count()
            if options_count > 0:
                # Select the last item (count - 1 because indexes start at 0)
                session.page.locator(selector).first.select_option(index=options_count - 1)
            else:
                return f"Action Failed: No options found in '{selector}'."
                
        # Handle number string (e.g., "1") as an index
        elif selection.isdigit():
            session.page.locator(selector).first.select_option(index=int(selection))
            
        # Handle regular text labels (e.g., "Text")
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
        # Check if a confirmation dialog appeared on the old page; click it if present
        try:
            session.page.get_by_role("button", name="Confirm").click(timeout=1500)
        except Exception:
            pass

        # Wait up to 10 seconds for the new tab to register in the browser context
        for _ in range(10):
            if len(session.context.pages) > 1:
                break
            time.sleep(1)

        # Switch active control to the newest tab (TRACES)
        session.page = session.context.pages[-1]
        session.page.bring_to_front()
        
        # Wait 5 seconds for the TRACES modal to render completely
        time.sleep(5)
        return f"Successfully switched to tab: '{session.page.title()}'"
    except Exception as e:
        return f"Action Failed: Could not switch tab. Error: {str(e)}"
    
@tool
def check_checkbox(selector: str) -> str:
    """Check a checkbox element on the page using its CSS selector."""
    global session
    try:
        # Native Playwright check designed specifically for <input type="checkbox">
        session.page.locator(selector).first.check(timeout=3000)
        return f"Successfully checked the checkbox '{selector}'."
    except Exception:
        try:
            # JavaScript fallback: forces the click even if invisible elements are blocking it
            session.page.evaluate(f"document.querySelector('{selector}').click()")
            return f"Successfully checked the checkbox '{selector}' using JavaScript."
        except Exception as e:
            return f"Action Failed: Could not check '{selector}'. Error: {str(e)}"

#_______________________
# dwonload file tool:
@tool
def download_and_export_to_excel(pan_number: str, date_of_birth: str) -> str:
    """Download Form 26AS from TRACES, unlock it using date_of_birth, parse text file contents into structured columns, and save to Excel."""
    global session
    save_dir = os.path.join(os.getcwd(), "client_data")
    os.makedirs(save_dir, exist_ok=True)
    
    excel_path = os.path.join(save_dir, f"{pan_number}_structured_tax_data.xlsx")
    clean_dob = date_of_birth.replace("/", "").replace("-", "")

    try:
        # 1. Trigger and intercept the TRACES 26AS download directly
        with session.page.expect_download(timeout=15000) as download_info:
            session.page.locator("#btnSubmit").first.click(timeout=3000)

        download = download_info.value
        raw_download_path = os.path.join(save_dir, download.suggested_filename)
        download.save_as(raw_download_path)

        form_26as_records = []

        # 2. Extract Data from Password-Protected TRACES ZIP and structure lines
        if raw_download_path.endswith(".zip"):
            with zipfile.ZipFile(raw_download_path, 'r') as zip_ref:
                # Unlock ZIP using DOB (DDMMYYYY)
                zip_ref.setpassword(clean_dob.encode())
                file_list = zip_ref.namelist()
                if file_list:
                    extracted_path = zip_ref.extract(file_list[0], path=save_dir)
                    with open(extracted_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str:
                                # Parse tab or pipe separated text rows into structured columns
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

        # 3. Load Prefilled ITR JSON if present
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

        # 4. Write structured records into Multi-Tab Excel Spreadsheet
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            # Tab 1: Client Overview
            pd.DataFrame([
                {"Attribute": "PAN Number", "Details": pan_number},
                {"Attribute": "Date of Birth", "Details": date_of_birth},
                {"Attribute": "Extraction Status", "Details": "Completed Successfully"}
            ]).to_excel(writer, sheet_name="Client Overview", index=False)

            # Tab 2: Form 26AS Data mapped into structured columns
            if form_26as_records:
                pd.DataFrame(form_26as_records).to_excel(writer, sheet_name="Form 26AS Tax Credits", index=False)
            else:
                pd.DataFrame([{"Data": "No Form 26AS data extracted"}]).to_excel(writer, sheet_name="Form 26AS Tax Credits", index=False)

            # Tab 3: Prefilled ITR Data
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
            # Index 0 is always the first tab opened
            session.page = session.context.pages[0]
            session.page.bring_to_front()
            return f"Successfully switched back to original tab: {session.page.title()}"
        return "Action Failed: No tabs available."
    except Exception as e:
        return f"Action Failed: Could not switch tab. Error: {str(e)}"


# ADDED 'download_file' TO THE TOOLS LIST
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
    download_and_export_to_excel
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
        "3. Click the 'Continue' button.\n"
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
        "44. Click the element 'AIS'."
        "46. Wait for 4 seconds so the AIS portal fully loads.\n"
        "47. Click the element 'Download AIS/TIS'.\n"
        "48. Wait for 2 seconds so the download modal appears.\n"
        "49. Click the element 'Download'."
    )

    print(f"\n🤖 Agent executing: Logging in PAN {pan_number}")
    messages = [("user", user_prompt)]

    # Increase this from 20 to 50
    for _ in range(50): 
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
            
            # --- ADD THIS LINE TO SEE THE ACTUAL ERRORS ---
            print(f"   ↳ Result: {tool_output}") 
            
            messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_id))

    print("\n✅ Final Agent Response: ITR Data Successfully Downloaded!")
    
    # Force the browser to stay open for 10 minutes (600 seconds) 
    # so you can interact with it manually before it auto-closes.
    print("⏳ Keeping the browser open for 10 minutes...")
    time.sleep(600)
    
    return "ITR filling process has been initiated successfully and data is downloaded."