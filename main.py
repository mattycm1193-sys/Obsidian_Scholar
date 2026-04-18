import sys
import os
from langgraph.graph import StateGraph, END
from src.agent_state import ScholarState
from src.nodes import planner_node, scraper_node, curator_node
from dotenv import load_dotenv

load_dotenv()

# Define the routing logic (Does the loop continue?)
def route_next_step(state: ScholarState):
    """If we have unvisited URLs in the queue, keep scraping. Otherwise, End."""
    unvisited = state.get("unvisited_urls", [])
    visited = state.get("visited_urls", [])
    
    if len(unvisited) > 0 and len(visited) < 5: # Limit to 5 loops for testing
        return "scraper"
    return END

def main():
    # 1. Dynamic CLI Arguments
    if len(sys.argv) < 2:
        print('Usage: python main.py <URL> "<Optional Research Goal>"')
        sys.exit(1)
        
    target_url = sys.argv[1]
    
    # If the user doesn't provide a specific goal, default to a general extraction
    if len(sys.argv) > 2:
        research_goal = sys.argv[2]
    else:
        research_goal = "Extract all documentation and core content from this site. Ignore pricing, login pages, language selectors, or generic navigation links."
    
    print(f"🚀 Initializing Autonomous Obsidian Scholar...")
    print(f"🎯 Target: {target_url}")
    print(f"🧠 Goal: {research_goal}")
    
    # Ensure Playwright is ready
    os.system("python -m playwright install chromium")
    
    # Build the Graph
    workflow = StateGraph(ScholarState)
    
    # Add Nodes
    workflow.add_node("scraper", scraper_node)
    workflow.add_node("curator", curator_node)
    workflow.add_node("planner", planner_node)
    
    # Define Edges (The Flow)
    workflow.set_entry_point("scraper")
    workflow.add_edge("scraper", "curator")
    workflow.add_edge("curator", "planner")
    workflow.add_conditional_edges("planner", route_next_step)
    
    # Compile the Agent
    app = workflow.compile()
    
    # Seed the Initial State
    initial_state = {
        "research_goal": research_goal,
        "current_url": "",
        "unvisited_urls": [target_url], # Start the queue with the provided URL
        "visited_urls": [],
        "raw_markdown": "",
        "raw_html": "",
        "error": ""
    }
    
    # Execute the Agent!
    app.invoke(initial_state)
    print("\n✨ Autonomous Knowledge assimilation complete. Check your vault!")

if __name__ == "__main__":
    main()
