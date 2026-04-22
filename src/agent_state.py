from typing import TypedDict, List, Annotated, Optional
import operator

# The State dictionary that gets passed between all LangGraph nodes
class ScholarState(TypedDict):
    # Core Mission Parameters (passed from UI)
    research_goal: str          # What the user actually wants (e.g., "Get all IL4 config guides")
    max_pages: int              # Limit for the scraping loop
    api_key: Optional[str]      # User-provided Gemini API key (optional, falls back to .env)
    vault_path: Optional[str]   # User-provided Obsidian vault path (optional, falls back to .env)
    
    # Internal Agent State
    current_url: str            # The URL currently being processed
    unvisited_urls: List[str]   # Queue of URLs the Planner decided are relevant
    visited_urls: Annotated[List[str], operator.add] # URLs we've already scraped (appends automatically)
    raw_markdown: str           # The scraped content from the current URL
    raw_html: str               # The raw DOM before parsing
    error: str                  # Any errors that occur during fetching
