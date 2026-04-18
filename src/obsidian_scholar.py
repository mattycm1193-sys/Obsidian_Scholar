import os
import re
import json
import logging
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import html2text
from google import genai  # <-- NEW SDK IMPORT
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Initialize Environment & Logging
load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("scholar.log"), logging.StreamHandler()]
)
logger = logging.getLogger("ObsidianScholar")

# Configure Gemini using the new SDK
# The client automatically detects the GEMINI_API_KEY from your .env file
client = genai.Client()

# Main Class
class ObsidianScholar:
    def __init__(self, vault_path=None, max_depth=None):
        self.vault_path = vault_path or os.getenv("OBSIDIAN_VAULT_PATH")
        self.max_depth = int(max_depth or os.getenv("MAX_CRAWL_DEPTH", 1))
        self.visited = set()
        self.h = html2text.HTML2Text()
        self.h.ignore_links = False
        self.h.body_width = 0 # Prevent arbitrary line wrapping

        if not os.path.exists(self.vault_path):
            os.makedirs(self.vault_path)
            logger.info(f"Created new vault directory at {self.vault_path}")

    def _sanitize_filename(self, title: str) -> str:
        """Removes illegal OS characters from titles."""
        clean = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        return clean[:100] # Limit length

    def _get_semantic_metadata(self, title: str, content: str, url: str) -> dict:
        """Leverages Gemini to classify, summarize, and tag the content."""
        prompt = f"""
        You are an expert knowledge curator managing an Obsidian Vault.
        Analyze the following web content.
        URL: {url}
        Title: {title}
        Content Snippet: {content[:3000]}

        Based on the content, provide the following in STRICT JSON format:
        {{
            "path": "The logical folder path relative to the vault root (e.g., '02 - ENGINEERING & INFRA/Python' or '05 - RESOURCES & CLIPPINGS/Articles'). Use the vault's established numbered directory structure if applicable.",
            "summary": "A concise, 2-sentence summary of the content.",
            "tags": ["tag1", "tag2", "tag3"],
            "aliases": ["Alternative Title 1", "Concept Name"]
        }}
        Return ONLY valid JSON. Do not include markdown formatting blocks like ```json.
        """
        try:
            # <-- NEW SDK CALL FORMAT
            response = client.models.generate_content(
                model='gemini-3.1-pro-previewcustomtools',
                contents=prompt
            )
            raw_text = response.text.strip()
            
            # Clean up potential markdown artifacts
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:-3].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:-3].strip()
                
            return json.loads(raw_text)
        except Exception as e:
            logger.error(f"Gemini metadata generation failed for {url}: {e}")
            return {
                "path": "05 - RESOURCES & CLIPPINGS/_INBOX",
                "summary": "Automated clipping. AI summarization failed.",
                "tags": ["clipping", "needs-review"],
                "aliases": []
            }

    def fetch_dynamic_content(self, url: str) -> str:
        """Uses Playwright to render JavaScript-heavy pages."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=15000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logger.warning(f"Playwright failed for {url}, falling back to requests. Error: {e}")
            import requests
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text

    def save_to_obsidian(self, title: str, content: str, source_url: str):
        """Generates frontmatter and saves the markdown file."""
        meta = self._get_semantic_metadata(title, content, source_url)
        category_path = meta.get('path', '05 - RESOURCES & CLIPPINGS/_INBOX')
        full_dir = os.path.join(self.vault_path, category_path)
        os.makedirs(full_dir, exist_ok=True)

        clean_title = self._sanitize_filename(title or "Untitled_Scrape")
        filename = f"{clean_title}.md"
        full_path = os.path.join(full_dir, filename)

        # Format YAML Frontmatter
        tags_str = "\n  - ".join(meta.get('tags', ['clipping']))
        aliases_str = "\n  - ".join(meta.get('aliases', []))
        date_str = os.popen('date +%Y-%m-%d').read().strip() if os.name != 'nt' else 'Today'
        
        frontmatter = f"""---
title: "{clean_title}"
source: {source_url}
date_scraped: {date_str}
summary: "{meta.get('summary', '')}"
tags:
  - {tags_str}
aliases:
  - {aliases_str}
---
# {clean_title}

"""
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(frontmatter)
            f.write(content)
        logger.info(f"✅ Successfully filed: [{category_path}/{filename}]")

    def crawl(self, url: str, depth=0):
        """Recursive crawler with depth control and deduplication."""
        if depth > self.max_depth or url in self.visited:
            return
        self.visited.add(url)
        logger.info(f"Crawling (Depth {depth}/{self.max_depth}): {url}")
        
        try:
            html = self.fetch_dynamic_content(url)
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove unnecessary elements to clean up markdown
            for script in soup(["script", "style", "nav", "footer", "iframe"]):
                script.decompose()
                
            markdown_content = self.h.handle(str(soup))
            title = soup.title.string if soup.title else urlparse(url).path.split('/')[-1]
            
            self.save_to_obsidian(title, markdown_content, url)
            
            # Recursive Link Extraction
            if depth < self.max_depth:
                for link in soup.find_all('a', href=True):
                    full_url = urljoin(url, link['href'])

                    
                    # 1. Skip non-English language paths and sneaky query parameters (like &hl=es or ?lang=fr)
                    if re.search(r'/(es|fr|de|zh|ja|ko|ru|pt|it|nl|pl)/|[?&](hl|lang|locale)=(?!en)', full_url.lower()):
                        continue


                    # 2. Strict domain matching to prevent escaping the target site
                    if urlparse(full_url).netloc == urlparse(url).netloc:
                        if "#" not in full_url: # Ignore anchor links
                            self.crawl(full_url, depth + 1)

        except Exception as e:
            logger.error(f"❌ Failed to process {url}: {e}")
