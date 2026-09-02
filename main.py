import os
import pymupdf  
import easyocr
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma  
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

from fill_the_data import run_itr_bot

load_dotenv()

PERSIST_DIR = "./chroma_fr_db"
PDF_PATH = "AIR1 FR Concept Book For May 26.pdf"
chat_history = []
retriever = None 
llm_with_tools = None

# ==========================================
# 1. Define Tools 
# ==========================================
@tool
def fill_itr_tool(pan_number: str, password: str, date_of_birth: str) -> str:
    """Call this tool ONLY to start the ITR filing process. 
    You MUST ask the user for their PAN number, password and date of birth in pannumber before calling this tool."""
    # Triggers the lightning-fast playwright bot in a background thread
    asyncio.create_task(asyncio.to_thread(run_itr_bot, pan_number, password,date_of_birth))
    return "I have securely launched the autonomous Playwright agent. The Chrome browser is opening now to fill your ITR."

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
    global retriever, llm_with_tools
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

@app.post("/chat")
async def ask_question(request: QueryRequest):
    global chat_history, llm_with_tools
    
    if not llm_with_tools:
        raise HTTPException(status_code=500, detail="Agent System not initialized")
    
    try:
        system_msg = SystemMessage(
            content="You are TaxCore AI, an autonomous CA assistant. "
                    "If the user asks to fill their ITR, you MUST ask for their PAN number, password, and birthdate first. "
                    "Only after they provide all three, trigger the fill_itr_tool. "
                    "If they ask a knowledge question, use search_ca_fr_knowledge."
        )
        
        user_msg = HumanMessage(content=request.message)
        messages = [system_msg] + chat_history + [user_msg]
        
        response = llm_with_tools.invoke(messages)
        
        if response.tool_calls:
            messages.append(response) 
            
            for tool_call in response.tool_calls:
                print(f"🔧 Agent calling tool: {tool_call['name']}")
                selected_tool = tool_map[tool_call["name"]]
                tool_output = selected_tool.invoke(tool_call["args"])
                messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_call["id"]))
            
            final_response = llm_with_tools.invoke(messages)
            chat_history.extend([user_msg, AIMessage(content=final_response.content)])
            return {"reply": final_response.content}
        
        chat_history.extend([user_msg, AIMessage(content=response.content)])
        return {"reply": response.content}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Ensure your HTML, JS, and CSS files are in a folder named 'static2'
app.mount("/", StaticFiles(directory="static2", html=True), name="static2")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting CA Platform on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)