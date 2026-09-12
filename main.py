import os
import pymupdf  
import easyocr
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.documents import Document
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma  
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fill_the_data import captcha_state
from langchain_core.tools import tool
import threading
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
import operator
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

from fill_the_data import run_itr_bot

load_dotenv()

PERSIST_DIR = "./chroma_fr_db"
PDF_PATH = "AIR1 FR Concept Book For May 26.pdf"
chat_history = []
retriever = None 
llm = None
llm_with_tools = None

# --- Global State Tracker ---
user_session = {
    "data_downloaded": False,
    "asked_profession": False,
    "professions": [], # Will hold ['salary', 'business', etc.]
    "current_profession_idx": 0
}

# ==========================================
# 1. Define Tools 
# ==========================================
@tool
def fill_itr_tool(pan_number: str, password: str, date_of_birth: str) -> str:
    """Call this tool ONLY to start the ITR filing process. 
    You MUST ask the user for their PAN number, password and date of birth before calling this tool."""
    global user_session
    
    # Reset state for a fresh run
    user_session["data_downloaded"] = False
    user_session["asked_profession"] = False
    user_session["professions"] = []
    user_session["current_profession_idx"] = 0

    def background_task():
        global user_session
        try:
            print("🚀 Starting background Playwright task...")
            run_itr_bot(pan_number, password, date_of_birth)
            user_session["data_downloaded"] = True
            print("✅ Background task complete. Data downloaded.")
        except Exception as e:
            print(f"❌ Playwright Bot Error: {e}")

    thread = threading.Thread(target=background_task)
    thread.start()
    
    return "I have securely launched the autonomous agent. Please wait a moment while I download your data..."

@tool
def search_ca_fr_knowledge(query: str) -> str:
    """Use this tool to search the database for CA syllabus, Financial Reporting (FR) concepts, and tax rules."""
    global retriever
    if retriever:
        docs = retriever.invoke(query)
        return "\n\n".join([d.page_content for d in docs])
    return "Database not initialized."

tool_map = {
    "fill_itr_tool": fill_itr_tool,
    "search_ca_fr_knowledge": search_ca_fr_knowledge
}

# ==========================================
# 2. Initialize System
# ==========================================
def init_rag_system():
    global retriever, llm_with_tools,llm
    print("Initializing OCR Engine & RAG System...")
    
    if os.path.exists(PERSIST_DIR) and os.listdir(PERSIST_DIR):
        print(f"✅ Loading existing database at {PERSIST_DIR}...")
        vectorstore = Chroma(
            persist_directory=PERSIST_DIR, 
            embedding_function=OpenAIEmbeddings()
        )
    else:
        print("❌ No database found. Reading PDF and running OCR...")
        ocr_reader = easyocr.Reader(['en'])
        doc = pymupdf.open(PDF_PATH)
        documents = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)
            image_bytes = pix.tobytes("png")
            ocr_result = ocr_reader.readtext(image_bytes, detail=0)
            extracted_text = " ".join(ocr_result)
            documents.append(Document(
                page_content=extracted_text,
                metadata={"source": PDF_PATH, "page": page_num + 1}
            ))
            print(f"Processed Page {page_num + 1}/{len(doc)}")
            
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(documents)
        
        vectorstore = Chroma.from_documents(
            documents=splits, 
            embedding=OpenAIEmbeddings(),
            persist_directory=PERSIST_DIR
        )
        print("✅ Vector database created and saved!")

    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(list(tool_map.values()))
    print("✅ Autonomous Agent successfully initialized!")

# ==========================================
# 3. FastAPI App Setup
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_rag_system()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

class QueryRequest(BaseModel):
    message: str 
class CaptchaSubmit(BaseModel):
    text: str

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]

# --- Node 1: Standard Chat & Tools ---
def general_chat_node(state: AgentState):
    system_msg = SystemMessage(
        content="You are TaxCore AI, an autonomous CA assistant. "
                "If the user asks to fill their ITR, you MUST ask for their PAN number, password, and birthdate first. "
                "Only after they provide all three, trigger the fill_itr_tool. "
                "If they ask a knowledge question, use search_ca_fr_knowledge."
    )
    # Inject the system message before the conversation history
    messages = [system_msg] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

# --- Node 2: Ask Profession ---
def ask_profession_node(state: AgentState):
    global user_session
    user_session["asked_profession"] = True
    msg = AIMessage(content="✅ **All ITR data has been successfully downloaded!**\n\nBefore we build your filing strategy, what is your profession/source of income? (You can choose multiple):\n- **Salary**\n- **Business**\n- **Agriculture**")
    return {"messages": [msg]}

# --- Node 3, 4, 5: Placeholder Nodes for your future questions ---
def salary_agent_node(state: AgentState):
    msg = [SystemMessage(content="""You are the Salary Tax Agent. Ask the next relevant salary question.
                                    ask questions like 1. enter your form 16.""")] + state["messages"]
    response = llm.invoke(msg)
    return {"messages": [response]}

def business_agent_node(state: AgentState):
    msg = [SystemMessage(content="You are the Business Tax Agent. Ask the next relevant business question.")] + state["messages"]
    response = llm.invoke(msg)
    return {"messages": [response]}

def agriculture_agent_node(state: AgentState):
    msg = [SystemMessage(content="You are the Agriculture Tax Agent. Ask the next relevant agriculture question.")] + state["messages"]
    response = llm.invoke(msg)
    return {"messages": [response]}

# --- Conditional Edge (The Router) ---
# --- Conditional Edge (The Router) ---
def route_conversation(state: AgentState) -> str:
    global user_session
    last_message = state["messages"][-1].content.lower() if state["messages"] else ""

    # 1. If data is downloaded but we haven't asked about profession yet
    if user_session["data_downloaded"] and not user_session["asked_profession"]:
        return "ask_profession"

    # 2. If we just asked for the profession, parse the user's answer
    if user_session["asked_profession"] and not user_session["professions"]:
        if "salary" in last_message: user_session["professions"].append("salary")
        if "business" in last_message: user_session["professions"].append("business")
        if "agriculture" in last_message or "agri" in last_message: user_session["professions"].append("agriculture")
        
        # If they didn't answer properly, keep them in general chat to clarify
        if not user_session["professions"]:
            return "general_chat"
        
        # Reset index to start with the first chosen profession
        user_session["current_profession_idx"] = 0

    # 3. If we have active professions in the queue, route to the current one
    if user_session["professions"]:
        if user_session["current_profession_idx"] < len(user_session["professions"]):
            active_prof = user_session["professions"][user_session["current_profession_idx"]]
            
            if active_prof == "salary":
                return "salary_agent"
            elif active_prof == "business":
                return "business_agent"
            elif active_prof == "agriculture":
                return "agriculture_agent"
        else:
            # All profession questionnaires are finished! Reset back to general chat
            return "general_chat"

    # Default fallback
    return "general_chat"

# --- Build the Graph ---
workflow = StateGraph(AgentState)

workflow.add_node("general_chat", general_chat_node)
workflow.add_node("tools", ToolNode(list(tool_map.values()))) # <--- NEW: Executes your tools
workflow.add_node("ask_profession", ask_profession_node)
workflow.add_node("salary_agent", salary_agent_node)
workflow.add_node("business_agent", business_agent_node)
workflow.add_node("agriculture_agent", agriculture_agent_node)

# START routes to the correct node based on the user_session
workflow.add_conditional_edges(START, route_conversation)

# General Chat either ends, or routes to the 'tools' node if a tool is called
workflow.add_conditional_edges("general_chat", tools_condition)
# After a tool finishes executing, it MUST return to general_chat to read the result
workflow.add_edge("tools", "general_chat") 

workflow.add_edge("ask_profession", END)
workflow.add_edge("salary_agent", END)
workflow.add_edge("business_agent", END)
workflow.add_edge("agriculture_agent", END)

app_graph = workflow.compile()

@app.get("/check-captcha")
async def check_captcha():
    return {"image": captcha_state["image"]}

@app.post("/submit-captcha")
async def submit_captcha(request: CaptchaSubmit):
    captcha_state["text"] = request.text
    return {"status": "success"}
@app.post("/chat")
async def ask_question(request: QueryRequest):
    global chat_history, llm_with_tools, app_graph
    
    if not llm_with_tools:
        raise HTTPException(status_code=500, detail="Agent System not initialized")
    
    try:
        user_msg = HumanMessage(content=request.message)
        chat_history.append(user_msg)
        
        # Capture the length of history BEFORE running the graph
        history_length_before = len(chat_history)
        
        result = app_graph.invoke({"messages": chat_history})
        
        # Extract ALL new messages generated by the graph (AI responses + Tool calls + Tool outputs)
        new_messages = result["messages"][history_length_before:]
        
        # Append all new messages safely to the global history
        chat_history.extend(new_messages)
        
        # The final AI reply to send to the frontend is always the last message
        final_ai_msg = result["messages"][-1]
        
        return {"reply": final_ai_msg.content}
        
    except Exception as e:
        print(f"Error in chat route: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/check-download-status")
async def check_download_status():
    global user_session, chat_history, app_graph
    
    if user_session.get("data_downloaded") and not user_session.get("asked_profession"):
        # Actually invoke the graph so ask_profession_node runs
        result = app_graph.invoke({"messages": chat_history})
        history_length_before = len(chat_history)
        new_messages = result["messages"][history_length_before:]
        chat_history.extend(new_messages)
        
        final_msg = result["messages"][-1]
        return {"status": "ready", "message": final_msg.content}
    
    return {"status": "pending"}

# Ensure your HTML, JS, and CSS files are in a folder named 'static2'
app.mount("/", StaticFiles(directory="static2", html=True), name="static2")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting CA Platform on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)