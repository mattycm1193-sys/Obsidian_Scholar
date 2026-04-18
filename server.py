import os
import json
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from src.agent_state import ScholarState
from src.nodes import planner_node, scraper_node, curator_node

load_dotenv()

app = FastAPI(title="Obsidian Scholar API")

# Allow the frontend UI to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "C:/Users/matty/Vaults/MCM_REMOTE")

# LangGraph Logic
def route_next_step(state: ScholarState):
    unvisited = state.get("unvisited_urls", [])
    visited = state.get("visited_urls", [])
    limit = state.get("max_pages", 5)
    
    if len(unvisited) > 0 and len(visited) < limit:
        return "scraper"
    return END

# Build the Graph Once
workflow = StateGraph(ScholarState)
workflow.add_node("scraper", scraper_node)
workflow.add_node("curator", curator_node)
workflow.add_node("planner", planner_node)
workflow.set_entry_point("scraper")
workflow.add_edge("scraper", "curator")
workflow.add_edge("curator", "planner")
workflow.add_conditional_edges("planner", route_next_step)
scholar_app = workflow.compile()

# API Schemas
class LaunchRequest(BaseModel):
    url: str
    goal: str
    max_pages: int

@app.post("/api/launch")
def launch_scholar(req: LaunchRequest):
    """Triggers the Agentic Loop"""
    os.system("python -m playwright install chromium")
    initial_state = {
        "research_goal": req.goal,
        "current_url": "",
        "unvisited_urls": [req.url],
        "visited_urls": [],
        "raw_markdown": "",
        "raw_html": "",
        "error": "",
        "max_pages": req.max_pages
    }
    final_state = scholar_app.invoke(initial_state)
    return {"status": "success", "visited_urls": final_state.get("visited_urls", [])}

@app.get("/api/vault")
def get_vault_files():
    """Returns a list of all markdown files scraped to display in the UI"""
    if not os.path.exists(VAULT_PATH):
        return {"files": []}
    
    md_files = []
    for root, _, files in os.walk(VAULT_PATH):
        for file in files:
            if file.endswith(".md"):
                rel_path = os.path.relpath(os.path.join(root, file), VAULT_PATH)
                # Ensure slashes are correct for web JSON
                md_files.append({"filename": file, "path": rel_path.replace('\\', '/')})
    return {"files": md_files}

@app.get("/api/vault/content")
def get_vault_content(path: str):
    """Returns the text of a specific file for the Vault View modal"""
    full_path = os.path.join(VAULT_PATH, path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return {"content": content}

@app.get("/api/graph")
def get_graph_data():
    """Generates basic nodes/edges for the D3 visualization"""
    files = get_vault_files()["files"]
    nodes = [{"id": "seed", "label": "Seed URL", "group": 1}]
    links = []
    
    for f in files:
        nodes.append({"id": f["filename"], "label": f["filename"], "group": 2})
        links.append({"source": "seed", "target": f["filename"]})
        
    return {"nodes": nodes, "links": links}

if __name__ == "__main__":
    print("🚀 API Server starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
