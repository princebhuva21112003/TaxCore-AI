# import pymupdf  # Updated to avoid PyMuPDF deprecation warning
# import easyocr
# from langchain_core.documents import Document
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain_chroma import Chroma  # Updated to standalone langchain-chroma package
# from langchain_openai import OpenAIEmbeddings, ChatOpenAI
# from langchain_classic.chains import create_retrieval_chain
# from langchain_classic.chains.combine_documents import create_stuff_documents_chain
# from langchain_core.prompts import ChatPromptTemplate
# from dotenv import load_dotenv

# load_dotenv()

# # Initialize EasyOCR for English
# print("Initializing OCR Engine...")
# ocr_reader = easyocr.Reader(['en'])

# def load_scanned_pdf(pdf_path: str):
#     """Converts photo PDF pages into LangChain Document objects using OCR."""
#     doc = pymupdf.open(pdf_path)  # Updated fitz.open to pymupdf.open
#     documents = []

#     print(f"Total Pages to Process: {len(doc)}")
    
#     for page_num in range(len(doc)):
#         page = doc[page_num]
#         # Render PDF page to an image
#         pix = page.get_pixmap(dpi=150)
#         image_bytes = pix.tobytes("png")
        
#         # Extract text from the image using OCR
#         ocr_result = ocr_reader.readtext(image_bytes, detail=0)
#         extracted_text = " ".join(ocr_result)
        
#         # Wrap into a LangChain Document object with metadata
#         documents.append(
#             Document(
#                 page_content=extracted_text,
#                 metadata={"source": pdf_path, "page": page_num + 1}
#             )
#         )
#         print(f"Processed Page {page_num + 1}/{len(doc)}")

#     return documents

# # 1. LOAD PHOTO PDF WITH OCR
# docs = load_scanned_pdf("AIR1 FR Concept Book For May 26.pdf")

# # 2. CHUNK THE EXTRACTED TEXT
# text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
# splits = text_splitter.split_documents(docs)

# # 3. STORE IN VECTOR DATABASE
# vectorstore = Chroma.from_documents(documents=splits, embedding=OpenAIEmbeddings())
# retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# # 4. RAG PROMPT & CHAIN
# system_prompt = (
#     "You are an expert Financial Reporting (FR) assistant. "
#     "Answer the question using the retrieved context. If unsure, say you don't know.\n\n"
#     "{context}"
# )

# prompt = ChatPromptTemplate.from_messages([
#     ("system", system_prompt),
#     ("human", "{input}"),
# ])

# question_answer_chain = create_stuff_documents_chain(ChatOpenAI(model="gpt-4o-mini"), prompt)
# rag_chain = create_retrieval_chain(retriever, question_answer_chain)

# # 5. QUERY YOUR NOTES
# response = rag_chain.invoke({"input": "give me Depreciation methods"})
# print("\n--- AI ANSWER ---")
# print(response["answer"])

import os  # Added to check for folders on your computer
import pymupdf  
import easyocr
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma  
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

load_dotenv()

# Define the folder where you want to permanently save the database
PERSIST_DIR = "./chroma_fr_db"

print("Initializing OCR Engine...")
ocr_reader = easyocr.Reader(['en'])

def load_scanned_pdf(pdf_path: str):
    """Converts photo PDF pages into LangChain Document objects using OCR."""
    doc = pymupdf.open(pdf_path)  
    documents = []

    print(f"Total Pages to Process: {len(doc)}")
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # Render PDF page to an image
        pix = page.get_pixmap(dpi=150)
        image_bytes = pix.tobytes("png")
        
        # Extract text from the image using OCR
        ocr_result = ocr_reader.readtext(image_bytes, detail=0)
        extracted_text = " ".join(ocr_result)
        
        # Wrap into a LangChain Document object with metadata
        documents.append(
            Document(
                page_content=extracted_text,
                metadata={"source": pdf_path, "page": page_num + 1}
            )
        )
        print(f"Processed Page {page_num + 1}/{len(doc)}")

    return documents

# --- CONDITIONAL DATABASE LOADING ---

# Check if the database folder already exists and has files inside it
if os.path.exists(PERSIST_DIR) and os.listdir(PERSIST_DIR):
    print(f"\n✅ Found existing database at {PERSIST_DIR}. Loading without reading the PDF...")
    # Load the existing database from disk
    vectorstore = Chroma(
        persist_directory=PERSIST_DIR, 
        embedding_function=OpenAIEmbeddings() # The embedding function is needed again to embed the query
    )
else:
    print("\n❌ No database found. Reading the PDF and running OCR (This will take a while)...")
    # 1. LOAD PHOTO PDF WITH OCR
    docs = load_scanned_pdf("AIR1 FR Concept Book For May 26.pdf")

    # 2. CHUNK THE EXTRACTED TEXT
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(docs)

    # 3. STORE IN VECTOR DATABASE AND SAVE TO DISK
    vectorstore = Chroma.from_documents(
        documents=splits, 
        embedding=OpenAIEmbeddings(),
        persist_directory=PERSIST_DIR  # This tells LangChain to save the database to your hard drive
    )
    print(f"\n✅ Vector database successfully created and saved to {PERSIST_DIR} for future use!")

# 4. RAG PROMPT & CHAIN
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

system_prompt = (
    "You are an expert Financial Reporting (FR) assistant. "
    "Answer the question using the retrieved context. If unsure, say you don't know.\n\n"
    "{context}"
)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
])

question_answer_chain = create_stuff_documents_chain(ChatOpenAI(model="gpt-5.6-terra"), prompt)
rag_chain = create_retrieval_chain(retriever, question_answer_chain)

# 5. QUERY YOUR NOTES
response = rag_chain.invoke({"input": "give me in sort form about Business combination through Acquisition of Net Assets "})
print("\n--- AI ANSWER ---")
print(response["answer"])