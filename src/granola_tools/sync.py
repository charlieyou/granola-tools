import argparse
import logging
from pathlib import Path
import json
import os
import time
import requests
from datetime import datetime, timezone
from functools import wraps

from .token_manager import TokenManager
from .config import get_granola_home, is_configured, load_config

LOG_FILE = get_granola_home() / "sync.log"

# Configurable client version (update when Granola updates)
DEFAULT_CLIENT_VERSION = "5.354.0"


def get_client_version() -> str:
    """Get client version from config or use default."""
    config = load_config()
    return config.get("client_version", DEFAULT_CLIENT_VERSION)


def get_headers(token: str) -> dict:
    """Build API request headers."""
    version = get_client_version()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": f"Granola/{version}",
        "X-Client-Version": version
    }


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, backoff_factor: float = 2.0):
    """Decorator for retrying requests with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.RequestException as e:
                    last_exception = e
                    # Don't retry on auth errors
                    if hasattr(e, 'response') and e.response is not None:
                        if e.response.status_code in (401, 403):
                            raise
                    
                    if attempt < max_retries - 1:
                        delay = base_delay * (backoff_factor ** attempt)
                        logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}), retrying in {delay:.1f}s: {e}")
                        time.sleep(delay)
                    else:
                        logger.error(f"Request failed after {max_retries} attempts: {e}")
            raise last_exception
        return wrapper
    return decorator


class APIResponseError(Exception):
    """Raised when API response format is unexpected."""
    pass


def validate_documents_response(response: dict) -> list:
    """Validate and extract documents from API response."""
    if not isinstance(response, dict):
        raise APIResponseError(f"Expected dict response, got {type(response).__name__}")
    
    if "docs" not in response:
        raise APIResponseError(f"Missing 'docs' key in response. Keys: {list(response.keys())}")
    
    docs = response["docs"]
    if not isinstance(docs, list):
        raise APIResponseError(f"Expected 'docs' to be list, got {type(docs).__name__}")
    
    return docs


def validate_transcript_response(response) -> list | None:
    """Validate transcript response format."""
    if response is None:
        return None
    
    if not isinstance(response, list):
        logger.warning(f"Unexpected transcript format: expected list, got {type(response).__name__}")
        return None
    
    return response

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Sync state file for incremental sync
SYNC_STATE_FILE = ".granola_sync_state.json"


def load_sync_state(output_path: Path) -> dict:
    """Load sync state from file."""
    state_path = output_path / SYNC_STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception as e:
            logger.warning(f"Could not load sync state: {e}")
    return {"documents": {}, "last_sync": None}


def save_sync_state(output_path: Path, state: dict):
    """Save sync state to file."""
    state_path = output_path / SYNC_STATE_FILE
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    try:
        state_path.write_text(json.dumps(state, indent=2))
        logger.debug(f"Saved sync state to {state_path}")
    except Exception as e:
        logger.error(f"Could not save sync state: {e}")


def needs_sync(doc: dict, sync_state: dict) -> bool:
    """
    Check if a document needs to be synced.
    
    Returns True if:
    - Document is new (not in sync state)
    - Document has been updated since last sync
    """
    doc_id = doc.get("id")
    if not doc_id:
        return True
    
    stored = sync_state.get("documents", {}).get(doc_id)
    if not stored:
        return True
    
    current_updated = doc.get("updated_at")
    stored_updated = stored.get("updated_at")
    
    if not current_updated or not stored_updated:
        return True
    
    return current_updated > stored_updated


def check_config_exists():
    """
    Check if config.json exists, if not provide helpful error message

    Returns:
        bool: True if config exists, False otherwise
    """
    config_path = Path('config.json')
    if not config_path.exists():
        logger.error("Config file 'config.json' not found!")
        logger.error("Please create config.json from config.json.template:")
        logger.error("  1. Copy config.json.template to config.json")
        logger.error("  2. Add your refresh_token and client_id")
        logger.error("  3. See GETTING_REFRESH_TOKEN.md for instructions on obtaining tokens")
        return False
    return True

@retry_with_backoff(max_retries=3)
def _fetch_documents_page(token: str, offset: int, limit: int) -> dict:
    """Fetch a single page of documents (with retry)."""
    url = "https://api.granola.ai/v2/get-documents"
    headers = get_headers(token)
    data = {
        "limit": limit,
        "offset": offset,
        "include_last_viewed_panel": True
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()


def fetch_granola_documents(token, limit=100):
    """
    Fetch ALL documents from Granola API with pagination

    Args:
        token: Access token
        limit: Number of documents to fetch per request (default 100)

    Returns:
        dict: Combined response with all documents
    """
    all_documents = []
    offset = 0

    while True:
        try:
            logger.info(f"Fetching documents: offset={offset}, limit={limit}")
            result = _fetch_documents_page(token, offset, limit)

            docs = result.get("docs", [])
            if not docs:
                break

            all_documents.extend(docs)
            logger.info(f"Fetched {len(docs)} documents (total so far: {len(all_documents)})")

            if len(docs) < limit:
                break

            offset += limit

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching documents at offset {offset}: {str(e)}")
            if offset == 0:
                return None
            break

    logger.info(f"Total documents fetched: {len(all_documents)}")
    return {"docs": all_documents}

@retry_with_backoff(max_retries=3)
def fetch_workspaces(token):
    """
    Fetch workspaces from Granola API

    Args:
        token: Access token

    Returns:
        dict: Workspaces data or None if failed
    """
    url = "https://api.granola.ai/v1/get-workspaces"
    headers = get_headers(token)

    try:
        response = requests.post(url, headers=headers, json={})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching workspaces: {str(e)}")
        return None


@retry_with_backoff(max_retries=3)
def fetch_document_lists(token):
    """
    Fetch document lists (folders) from Granola API

    Args:
        token: Access token

    Returns:
        dict: Document lists data or None if failed
    """
    headers = get_headers(token)

    # Try v2 endpoint first, then v1
    endpoints = [
        "https://api.granola.ai/v2/get-document-lists",
        "https://api.granola.ai/v1/get-document-lists"
    ]

    for url in endpoints:
        try:
            logger.debug(f"Trying endpoint: {url}")
            response = requests.post(url, headers=headers, json={})
            response.raise_for_status()
            logger.info(f"Successfully fetched document lists from {url}")
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.debug(f"Endpoint {url} not found, trying next...")
                continue
            else:
                logger.error(f"Error fetching document lists from {url}: {str(e)}")
                continue
        except Exception as e:
            logger.error(f"Error fetching document lists from {url}: {str(e)}")
            continue

    logger.warning("All document list endpoints failed")
    return None

@retry_with_backoff(max_retries=3)
def _fetch_batch_page(token: str, document_ids: list) -> list:
    """Fetch a single batch of documents (with retry)."""
    url = "https://api.granola.ai/v1/get-documents-batch"
    headers = get_headers(token)
    data = {
        "document_ids": document_ids,
        "include_last_viewed_panel": True
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    return result.get("documents") or result.get("docs") or []


def fetch_documents_batch(token, document_ids, batch_size=100):
    """
    Fetch multiple documents by their IDs using the batch endpoint

    IMPORTANT: This is the ONLY way to fetch shared documents in folders.
    The regular get-documents endpoint does NOT return shared documents.

    Recommended workflow:
    1. Use fetch_document_lists() to get folder contents (returns document IDs)
    2. Use this function to fetch the actual documents (including shared ones)

    Args:
        token: Access token
        document_ids: List of document IDs to fetch
        batch_size: Number of documents to fetch per request (default 100)

    Returns:
        list: List of documents (including both owned and shared documents)
    """
    all_documents = []

    for i in range(0, len(document_ids), batch_size):
        batch = document_ids[i:i + batch_size]

        try:
            logger.info(f"Fetching batch {i // batch_size + 1}: {len(batch)} documents")
            docs = _fetch_batch_page(token, batch)
            all_documents.extend(docs)
            logger.info(f"Fetched {len(docs)} documents in batch {i // batch_size + 1}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching batch at index {i}: {str(e)}")
            continue

    logger.info(f"Total documents fetched via batch: {len(all_documents)}/{len(document_ids)}")
    return all_documents

@retry_with_backoff(max_retries=3)
def fetch_document_transcript(token, document_id):
    """
    Fetch transcript for a specific document

    Args:
        token: Access token
        document_id: Document ID to fetch transcript for

    Returns:
        list: Transcript data (list of utterances) or None if not found
    """
    url = "https://api.granola.ai/v1/get-document-transcript"
    headers = get_headers(token)
    data = {
        "document_id": document_id
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return validate_transcript_response(result)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.debug(f"No transcript found for document {document_id}")
            return None
        else:
            logger.error(f"Error fetching transcript for {document_id}: {str(e)}")
            return None
    except Exception as e:
        logger.error(f"Error fetching transcript for {document_id}: {str(e)}")
        return None

def convert_prosemirror_to_markdown(content):
    """
    Convert ProseMirror JSON to Markdown
    """
    if not content or not isinstance(content, dict) or 'content' not in content:
        return ""
        
    markdown = []
    
    def process_node(node):
        if not isinstance(node, dict):
            return ""
            
        node_type = node.get('type', '')
        content = node.get('content', [])
        text = node.get('text', '')
        
        if node_type == 'heading':
            level = node.get('attrs', {}).get('level', 1)
            heading_text = ''.join(process_node(child) for child in content)
            return f"{'#' * level} {heading_text}\n\n"
            
        elif node_type == 'paragraph':
            para_text = ''.join(process_node(child) for child in content)
            return f"{para_text}\n\n"
            
        elif node_type == 'bulletList':
            items = []
            for item in content:
                if item.get('type') == 'listItem':
                    item_content = ''.join(process_node(child) for child in item.get('content', []))
                    items.append(f"- {item_content.strip()}")
            return '\n'.join(items) + '\n\n'
            
        elif node_type == 'text':
            return text
            
        return ''.join(process_node(child) for child in content)
    
    return process_node(content)

def convert_transcript_to_markdown(transcript_data):
    """
    Convert transcript JSON to formatted markdown
    
    Args:
        transcript_data: The transcript JSON response (list of utterances)
        
    Returns:
        str: Markdown formatted transcript
    """
    if not transcript_data or not isinstance(transcript_data, list):
        return "# Transcript\n\nNo transcript content available.\n"
    
    markdown = ["# Transcript\n\n"]
    
    for utterance in transcript_data:
        source = utterance.get('source', 'unknown')
        text = utterance.get('text', '')
        start_timestamp = utterance.get('start_timestamp', '')
        
        speaker = "Microphone" if source == "microphone" else "System"
        
        timestamp_str = ""
        if start_timestamp:
            try:
                dt = datetime.fromisoformat(start_timestamp.replace('Z', '+00:00'))
                timestamp_str = f"[{dt.strftime('%H:%M:%S')}]"
            except (ValueError, AttributeError):
                timestamp_str = ""
        
        markdown.append(f"**{speaker}** {timestamp_str}\n\n{text}\n\n")
    
    return ''.join(markdown)

def run_sync(output_dir: str, full: bool = False):
    """Run the sync process."""
    logger.info("Starting Granola sync process")
    
    output_path = Path(output_dir).expanduser()
    logger.info(f"Output directory set to: {output_path}")
    
    if not output_path.is_dir():
        logger.error(f"Output directory '{output_path}' does not exist or is not a directory.")
        logger.error("Please create it first.")
        return

    # Load sync state for incremental sync
    if full:
        logger.info("Full sync requested - ignoring previous sync state")
        sync_state = {"documents": {}, "last_sync": None}
    else:
        sync_state = load_sync_state(output_path)
        if sync_state.get("last_sync"):
            logger.info(f"Incremental sync - last sync was {sync_state['last_sync']}")
        else:
            logger.info("No previous sync state found - will sync all documents")

    logger.info("Initializing token manager...")
    token_manager = TokenManager()

    logger.info("Obtaining access token...")
    access_token = token_manager.get_valid_token()
    if not access_token:
        logger.error("Failed to obtain access token. Exiting.")
        return

    logger.info("Fetching workspaces from Granola API...")
    workspaces_response = fetch_workspaces(access_token)

    # Create workspace ID to name mapping
    workspace_map = {}
    if workspaces_response:
        logger.info(f"Successfully fetched workspaces")
        # Save workspaces response for reference
        workspaces_path = output_path / "workspaces.json"
        try:
            with open(workspaces_path, 'w', encoding='utf-8') as f:
                json.dump(workspaces_response, f, indent=2)
            logger.info(f"Workspaces data saved to {workspaces_path}")
        except Exception as e:
            logger.error(f"Failed to write workspaces to file: {str(e)}")

        # Build workspace map
        if isinstance(workspaces_response, list):
            for workspace in workspaces_response:
                workspace_id = workspace.get("id")
                workspace_name = workspace.get("name")
                if workspace_id:
                    workspace_map[workspace_id] = workspace_name
        elif isinstance(workspaces_response, dict) and "workspaces" in workspaces_response:
            for workspace in workspaces_response["workspaces"]:
                workspace_id = workspace.get("id")
                workspace_name = workspace.get("name")
                if workspace_id:
                    workspace_map[workspace_id] = workspace_name
    else:
        logger.warning("Could not fetch workspaces - workspace names will not be included in metadata")

    logger.info("Fetching document lists (folders) from Granola API...")
    document_lists_response = fetch_document_lists(access_token)

    # Create mapping of document ID to lists it belongs to
    document_to_lists_map = {}
    list_id_to_name_map = {}

    if document_lists_response:
        logger.info(f"Successfully fetched document lists")
        # Save document lists response for reference
        document_lists_path = output_path / "document_lists.json"
        try:
            with open(document_lists_path, 'w', encoding='utf-8') as f:
                json.dump(document_lists_response, f, indent=2)
            logger.info(f"Document lists data saved to {document_lists_path}")
        except Exception as e:
            logger.error(f"Failed to write document lists to file: {str(e)}")

        # Build document-to-lists mapping
        lists = []
        if isinstance(document_lists_response, list):
            lists = document_lists_response
        elif isinstance(document_lists_response, dict):
            if "lists" in document_lists_response:
                lists = document_lists_response["lists"]
            elif "document_lists" in document_lists_response:
                lists = document_lists_response["document_lists"]

        for doc_list in lists:
            list_id = doc_list.get("id")
            list_name = doc_list.get("name") or doc_list.get("title")

            if list_id and list_name:
                list_id_to_name_map[list_id] = list_name

            # Get documents in this list
            documents_in_list = doc_list.get("documents", [])
            if not documents_in_list:
                # Try other possible field names
                documents_in_list = doc_list.get("document_ids", [])

            for doc in documents_in_list:
                # Handle both dict and string formats
                if isinstance(doc, dict):
                    doc_id = doc.get("id") or doc.get("document_id")
                else:
                    doc_id = doc

                if doc_id:
                    if doc_id not in document_to_lists_map:
                        document_to_lists_map[doc_id] = []
                    document_to_lists_map[doc_id].append({
                        "id": list_id,
                        "name": list_name
                    })

        logger.info(f"Found {len(lists)} document lists with {len(document_to_lists_map)} documents organized")
    else:
        logger.warning("Could not fetch document lists - folder information will not be included in metadata")

    logger.info("Fetching documents from Granola API...")
    api_response = fetch_granola_documents(access_token)

    # Write the API response JSON to a file named "granola_api_response.json" in the output directory
    api_response_path = output_path / "granola_api_response.json"
    try:
        with open(api_response_path, 'w', encoding='utf-8') as f:
            json.dump(api_response, f, indent=2)
        logger.info(f"API response saved to {api_response_path}")
    except Exception as e:
        logger.error(f"Failed to write API response to file: {str(e)}")

    if not api_response:
        logger.error("Failed to fetch documents - API response is empty")
        return
    
    try:
        documents = validate_documents_response(api_response)
    except APIResponseError as e:
        logger.error(f"API response format error: {e}")
        return

    logger.info(f"Successfully fetched {len(documents)} documents from Granola")
    
    if not documents:
        logger.warning("No documents found in the API response")
        return

    synced_count = 0
    skipped_in_progress = 0
    skipped_unchanged = 0
    
    for doc in documents:
        title = doc.get("title", "Untitled Granola Note")
        doc_id = doc.get("id", "unknown_id")
        meeting_end_count = doc.get("meeting_end_count", 0)
        
        # Skip meetings that never ended (likely in-progress or abandoned)
        if meeting_end_count == 0:
            logger.info(f"Skipping in-progress/unended meeting: {title} (meeting_end_count=0)")
            skipped_in_progress += 1
            continue
        
        # Check if document needs sync (incremental)
        if not needs_sync(doc, sync_state):
            logger.debug(f"Skipping unchanged document: {title}")
            skipped_unchanged += 1
            continue
        
        logger.info(f"Processing document: {title} (ID: {doc_id})")
        
        doc_folder = output_path / doc_id
        doc_folder.mkdir(exist_ok=True)
        logger.debug(f"Created folder: {doc_folder}")
        
        try:
            document_json_path = doc_folder / "document.json"
            with open(document_json_path, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2)
            logger.debug(f"Saved raw document JSON to: {document_json_path}")
            
            transcript_data = fetch_document_transcript(access_token, doc_id)
            if transcript_data:
                transcript_json_path = doc_folder / "transcript.json"
                with open(transcript_json_path, 'w', encoding='utf-8') as f:
                    json.dump(transcript_data, f, indent=2)
                logger.debug(f"Saved raw transcript JSON to: {transcript_json_path}")
            
            workspace_id = doc.get("workspace_id")
            metadata = {
                "document_id": doc_id,
                "title": title,
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
                "workspace_id": workspace_id,
                "workspace_name": workspace_map.get(workspace_id) if workspace_id else None,
                "folders": document_to_lists_map.get(doc_id, []),
                "meeting_date": None,
                "sources": [],
                "meeting_end_count": meeting_end_count
            }
            
            if transcript_data and isinstance(transcript_data, list) and len(transcript_data) > 0:
                sources = list(set(utterance.get('source', 'unknown') for utterance in transcript_data))
                metadata["sources"] = sources
                
                first_utterance = transcript_data[0]
                if first_utterance.get('start_timestamp'):
                    metadata["meeting_date"] = first_utterance['start_timestamp']
            
            metadata_path = doc_folder / "metadata.json"
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            logger.debug(f"Saved metadata to: {metadata_path}")
            
            content_to_parse = None
            if doc.get("last_viewed_panel") and \
               isinstance(doc["last_viewed_panel"], dict) and \
               doc["last_viewed_panel"].get("content") and \
               isinstance(doc["last_viewed_panel"]["content"], dict) and \
               doc["last_viewed_panel"]["content"].get("type") == "doc":
                content_to_parse = doc["last_viewed_panel"]["content"]
            
            if content_to_parse:
                logger.debug(f"Converting document to markdown: {title}")
                markdown_content = convert_prosemirror_to_markdown(content_to_parse)
                
                resume_path = doc_folder / "resume.md"
                with open(resume_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {title}\n\n")
                    f.write(markdown_content)
                logger.debug(f"Saved resume to: {resume_path}")
            else:
                logger.warning(f"No content found for resume.md in document: {title}")
            
            if transcript_data:
                transcript_markdown = convert_transcript_to_markdown(transcript_data)
                transcript_md_path = doc_folder / "transcript.md"
                with open(transcript_md_path, 'w', encoding='utf-8') as f:
                    f.write(transcript_markdown)
                logger.debug(f"Saved transcript markdown to: {transcript_md_path}")
            else:
                logger.warning(f"No transcript available for document: {title}")
            
            # Update sync state for this document
            sync_state["documents"][doc_id] = {
                "updated_at": doc.get("updated_at"),
                "title": title,
                "synced_at": datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"Successfully processed document: {title}")
            synced_count += 1
            
            # Save sync state periodically (every 50 docs) to avoid losing progress
            if synced_count % 50 == 0:
                save_sync_state(output_path, sync_state)
                logger.info(f"Checkpoint: saved sync state after {synced_count} documents")
            
        except Exception as e:
            logger.error(f"Error processing document '{title}' (ID: {doc_id}): {str(e)}")
            logger.debug("Full traceback:", exc_info=True)

    # Save sync state
    save_sync_state(output_path, sync_state)
    
    logger.info(f"Sync complete:")
    logger.info(f"  - Synced: {synced_count} documents")
    logger.info(f"  - Skipped (in-progress/unended): {skipped_in_progress}")
    logger.info(f"  - Skipped (unchanged): {skipped_unchanged}")
    logger.info(f"  - Output: '{output_path}'")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Sync Granola meetings")
    parser.add_argument("output_dir", type=str, help="Output directory for transcripts")
    parser.add_argument("--full", action="store_true", help="Force full sync")
    args = parser.parse_args()
    run_sync(args.output_dir, full=args.full)


if __name__ == "__main__":
    main()
