from typing import TypedDict, List, Annotated
import operator

# The State dictionary that gets passed between all LangGraph nodes
class ScholarState(TypedDict):
    research_goal: str          # What the user actually wants
    current_url: str            # The URL currently being processed
    unvisited_urls: List[str]   # Queue of URLs the Planner decided are relevant
    visited_urls: Annotated[List[str], operator.add] # URLs we've already scraped
    raw_markdown: str           # The scraped content from the current URL
    raw_html: str               # The raw DOM
    error: str                  # Any errors that occur during fetching
    max_pages: int              # UI-controlled limit
