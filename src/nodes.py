import os
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import html2text
from google import genai
from playwright.sync_api import sync_playwright

from src.agent_state import ScholarState

def get_gemini_client(state: ScholarState):
    """
    Initializes the Gemini client dynamically. 
    Checks the UI state first, then falls back to the local .env file.
    Prevents server crash if the .env file is empty.
    """
    api_key = state.get("api_key") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Gemini API Key is missing. Please provide it in the UI or .env file.")
    return genai.Client(api_key=api_key)

def planner_node(state: ScholarState) -> ScholarState:
    """Analyzes the current page and extracts relevant links based on the research goal."""
    if not state.get("raw_html") or "error" in state:
        return state

    print(f"🧠 Planner: Analyzing links from {state['current_url']}...")
    soup = BeautifulSoup(state["raw_html"], 'html.parser')
    
    # Grab all links on the page
    all_links = []
    for a in soup.find_all('a', href=True):
        full_url = urljoin(state['current_url'], a['href'])
        all_links.append(full_url)
        
    # Deduplicate and remove anchor links or already visited links
    visited = state.get('visited_urls', [])
    unique_links = list(set([link for link in all_links if "#" not in link and link not in visited]))
    
    prompt = f"""
    You are an autonomous research agent.
    The user's goal is: "{state.get('research_goal', 'Extract core content.')}"
    
    Here are the URLs found on the current page:
    {unique_links[:100]}
    
    Return ONLY a JSON list of URLs from this list that are highly relevant to the user's goal.
    Ignore language selectors, login pages, unrelated blog posts, or generic navigation links.
    Return strictly a JSON array of strings: ["url1", "url2"]. No markdown formatting blocks.
    """
    
    try:
        client = get_gemini_client(state)
        response = client.models.generate_content(
            model='gemini-3.1-pro-previewcustomtools',
            contents=prompt
        )
        raw_text = response.text.strip()
        if raw_text.startswith("```json"): raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"): raw_text = raw_text[3:-3].strip()
            
        relevant_links = json.loads(raw_text)
        print(f"✅ Planner found {len(relevant_links)} relevant links.")
        
        # Combine existing unvisited with new relevant links, keeping them unique
        current_queue = state.get("unvisited_urls", [])
        new_queue = list(set(current_queue + relevant_links))
        
        return {"unvisited_urls": new_queue}
    except Exception as e:
        print(f"❌ Planner failed: {e}")
        return {"error": str(e)}

def scraper_node(state: ScholarState) -> ScholarState:
    """Pops the next URL, fetches it, and converts to Markdown."""
    queue = list(state.get("unvisited_urls", []))
    if not queue:
        return {"error": "No URLs left to scrape"}
    
    # Pop the first URL off the queue
    current_url = queue.pop(0)
    print(f"\n🕸️ Scraper: Fetching {current_url}...")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(current_url, wait_until="networkidle", timeout=15000)
            html = page.content()
            browser.close()
            
        h = html2text.HTML2Text()
        h.ignore_links = False
        markdown = h.handle(html)
        
        return {
            "current_url": current_url,
            "raw_html": html,
            "raw_markdown": markdown,
            "unvisited_urls": queue, 
            "visited_urls": [current_url] 
        }
    except Exception as e:
        print(f"❌ Scraper failed on {current_url}: {e}")
        return {"error": str(e), "unvisited_urls": queue}

def curator_node(state: ScholarState) -> ScholarState:
    """Uses Gemini to categorize the markdown and saves it to Obsidian."""
    if not state.get("raw_markdown") or "error" in state:
        return state

    print(f"📁 Curator: Filing into Obsidian...")
    prompt = f"""
    You are an expert knowledge curator for an Obsidian Vault.
    Analyze this content scraped from: {state['current_url']}
    
    Content Snippet: {state['raw_markdown'][:3000]}

    Return STRICT JSON format:
    {{
        "path": "The logical folder path relative to the vault root (e.g., '02 - ENGINEERING & INFRA/Solo.io').",
        "summary": "A 2-sentence summary.",
        "tags": ["api-gateway", "service-mesh"]
    }}
    """
    
    try:
        client = get_gemini_client(state)
        response = client.models.generate_content(
            model='gemini-3.1-pro-previewcustomtools', 
            contents=prompt
        )
        raw_text = response.text.strip()
        if raw_text.startswith("```json"): raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"): raw_text = raw_text[3:-3].strip()
        
        meta = json.loads(raw_text)
        
        # Determine Vault Path (UI State > Environment Variable > Default)
        vault_path = state.get("vault_path") or os.getenv("OBSIDIAN_VAULT_PATH", "./Obsidian_Inbox")
        category_path = meta.get('path', '05 - RESOURCES/Inbox')
        full_dir = os.path.join(vault_path, category_path)
        os.makedirs(full_dir, exist_ok=True)
        
        clean_title = re.sub(r'[\\/*?:"<>|]', "", state['current_url'].split('/')[-2] or "index")
        filepath = os.path.join(full_dir, f"{clean_title}.md")
        tags_str = "\n  - ".join(meta.get('tags', ['scholar']))
        
        frontmatter = f"---\nsource: {state['current_url']}\nsummary: {meta.get('summary')}\ntags:\n  - {tags_str}\n---\n\n"
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter + state['raw_markdown'])
            
        print(f"✅ Curator saved to: {category_path}/{clean_title}.md")
        return {"raw_markdown": ""} 
        
    except Exception as e:
        print(f"❌ Curator failed: {e}")
        return state
