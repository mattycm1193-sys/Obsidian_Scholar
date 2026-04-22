from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uvicorn
from dotenv import load_dotenv

# Import LangGraph components
from langgraph.graph import StateGraph, END
from src.agent_state import ScholarState
from src.nodes import planner_node, scraper_node, curator_node

load_dotenv()

app = FastAPI(title="Obsidian Scholar API")

# Enable CORS so the Stitch UI (running on localhost) can talk to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the data structure the UI will send to us
class ScholarRequest(BaseModel):
    seed_url: str
    research_goal: str
    max_pages: int = 5
    api_key: str = None
    vault_path: str = None

# LangGraph Routing Logic
def route_next_step(state: ScholarState):
    """If we have unvisited URLs in the queue, keep scraping. Otherwise, End."""
    unvisited = state.get("unvisited_urls", [])
    visited = state.get("visited_urls", [])
    limit = state.get("max_pages", 5)
    
    if len(unvisited) > 0 and len(visited) < limit: 
        return "scraper"
    return END

def build_agent():
    """Compiles the LangGraph workflow"""
    workflow = StateGraph(ScholarState)
    
    workflow.add_node("scraper", scraper_node)
    workflow.add_node("curator", curator_node)
    workflow.add_node("planner", planner_node)
    
    workflow.set_entry_point("scraper")
    workflow.add_edge("scraper", "curator")
    workflow.add_edge("curator", "planner")
    workflow.add_conditional_edges("planner", route_next_step)
    
    return workflow.compile()

@app.post("/api/launch")
async def launch_scholar(request: ScholarRequest):
    """The main endpoint the UI calls to start the agent loop."""
    print(f"🚀 Received API request for: {request.seed_url}")
    
    # Ensure Playwright is ready
    os.system("python -m playwright install chromium")
    
    agent_app = build_agent()
    
    # Build the initial state dictionary from the UI payload
    initial_state = {
        "research_goal": request.research_goal,
        "current_url": "",
        "unvisited_urls": [request.seed_url],
        "visited_urls": [],
        "raw_markdown": "",
        "raw_html": "",
        "error": "",
        "max_pages": request.max_pages,
        "api_key": request.api_key,
        "vault_path": request.vault_path
    }
    
    try:
        # Run the agent (This will block until the loop finishes)
        # Note: For a production UI, you'd want to stream these results back using WebSockets 
        # or Server-Sent Events (SSE) to update the terminal window in real-time.
        # For this MVP, we wait for completion and return the final state.
        final_state = agent_app.invoke(initial_state)
        
        return {
            "status": "success",
            "message": f"Successfully assimilated {len(final_state.get('visited_urls', []))} pages.",
            "pages_scraped": final_state.get('visited_urls', []),
            "errors": final_state.get('error', "")
        }
        
    except Exception as e:
        print(f"❌ Server Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """Simple check to ensure the server is running."""
    return {"status": "online", "agent": "Obsidian Scholar"}

if __name__ == "__main__":
    print("🔮 Starting Obsidian Scholar API Server on port 8000...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
