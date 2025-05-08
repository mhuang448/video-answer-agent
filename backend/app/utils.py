# app/utils.py
from datetime import datetime, timezone
import json
import os
import random
import re
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from dotenv import load_dotenv
import uuid
from typing import List, Optional, Dict, Any
import time # Added for Pinecone index readiness check
# Added imports for OpenAI and Pinecone
from openai import OpenAI, OpenAIError
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec
from pinecone.exceptions import PineconeException

from anthropic import Anthropic, AnthropicError

# Load .env file ONLY for local development.
# In production (App Runner), environment variables are set directly.
load_dotenv()

# --- Configuration Loading ---

def load_config() -> Dict[str, Any]: # Changed return type hint
    """Loads configuration from environment variables.
       PREVIOUSLY LOADED MCP SERVER CONFIG FROM JSON FILE; this is now deprecated in favor of MCP server SSE URL.
    """
    config = {
        "aws_region": os.getenv("AWS_REGION", "us-east-2"),
        "s3_bucket_name": os.getenv("S3_BUCKET_NAME"),
        "pinecone_api_key": os.getenv("PINECONE_API_KEY"),
        "pinecone_index_host": os.getenv("PINECONE_INDEX_HOST"), # May be set dynamically if not present
        "pinecone_index_name": os.getenv("PINECONE_INDEX_NAME", "video-captions-index"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "openai_embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),
        "openai_synthesis_model": os.getenv("OPENAI_SYNTHESIS_MODEL", "gpt-4o-mini"), # Added for synthesis
        "google_api_key": os.getenv("GOOGLE_API_KEY"), # Or handle GOOGLE_APPLICATION_CREDENTIALS
        "perplexity_api_key": os.getenv("PERPLEXITY_API_KEY"), # Needed for MCP server env
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"), # Needed for Claude tool selection
        "anthropic_tool_selection_model": os.getenv("ANTHROPIC_TOOL_SELECTION_MODEL", "claude-3-7-sonnet-20250219"), # Added for Anthropic
        # Add direct AWS keys only if absolutely needed (prefer IAM roles)
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        # "mcp_servers": {}, # Initialize mcp_servers dict, commenting out for now, reference to deprecated JSON mcp_config.json file
        # --- EDIT: Replace MCP server command/args with SSE URL ---
        "mcp_perplexity_sse_url": os.getenv("MCP_PERPLEXITY_SSE_URL"), # e.g., https://<host>/sse
        # --- END EDIT ---
    }

    # Basic validation
    if not config["s3_bucket_name"]:
        raise ValueError("Missing required environment variable: S3_BUCKET_NAME")
    if not config["pinecone_api_key"]:
        print("Warning: Missing PINECONE_API_KEY environment variable.")
    if not config["openai_api_key"]:
        print("Warning: Missing OPENAI_API_KEY environment variable.")
    if not config["perplexity_api_key"]:
         print("Warning: Missing PERPLEXITY_API_KEY environment variable (needed for Perplexity MCP server).")
    if not config["mcp_perplexity_sse_url"]:
         print("Warning: Missing MCP_PERPLEXITY_SSE_URL environment variable (URL of the deployed Perplexity MCP server's /sse endpoint).")
    if not config["anthropic_api_key"]:
        print("Warning: Missing ANTHROPIC_API_KEY environment variable (needed for Claude tool selection).")

    return config

CONFIG = load_config() # Load config once when the module is imported

# --- AWS S3 Client Setup ---

def get_s3_client():
    """Initializes and returns an S3 client."""
    try:
        s3_client = boto3.client(
            's3',
            region_name=CONFIG["aws_region"],
        )
        s3_client.head_bucket(Bucket=CONFIG["s3_bucket_name"])
        print(f"S3 Client Initialized Successfully for bucket '{CONFIG['s3_bucket_name']}'.")
        return s3_client
    except (NoCredentialsError, PartialCredentialsError):
        print("ERROR: AWS credentials not found.")
        raise
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchBucket':
            print(f"ERROR: S3 bucket '{CONFIG['s3_bucket_name']}' not found or access denied.")
        else:
            print(f"ERROR: Failed to initialize S3 client: {e}")
        raise
    except Exception as e:
        print(f"ERROR: Unexpected error initializing S3 client: {e}")
        raise

S3_CLIENT = get_s3_client() # Initialize client once

# --- OpenAI Client Setup ---
def get_openai_client():
    """Initializes and returns an OpenAI client."""
    api_key = CONFIG.get("openai_api_key")
    if not api_key:
        print("ERROR: OpenAI API key not configured.")
        return None # Allow graceful failure
    try:
        client = OpenAI(api_key=api_key)
        # client.models.list() # Optional: Test call
        print("OpenAI Client Initialized Successfully.")
        return client
    except OpenAIError as e:
        print(f"ERROR: Failed to initialize OpenAI client: {e}")
        raise
    except Exception as e:
        print(f"ERROR: Unexpected error initializing OpenAI client: {e}")
        raise

OPENAI_CLIENT = get_openai_client()

# --- Pinecone Client Setup ---
def get_pinecone_client_and_index():
    """Initializes Pinecone client and connects to the specified index."""
    api_key = CONFIG.get("pinecone_api_key")
    if not api_key:
        print("ERROR: Pinecone API key not configured.")
        return None, None # Allow graceful failure

    index_name = CONFIG.get("pinecone_index_name")
    index_host = CONFIG.get("pinecone_index_host")

    if not index_name:
        print("ERROR: Pinecone index name not configured.")
        return None, None

    try:
        print("Initializing Pinecone client...")
        pc = Pinecone(api_key=api_key)

        if not index_host:
            # Discover host if not set
            print(f"PINECONE_INDEX_HOST not set. Discovering host for index '{index_name}'...")
            existing_indexes = pc.list_indexes().names()
            try:
                if index_name not in existing_indexes:
                    raise ValueError(f"Pinecone index '{index_name}' does not exist.")

                index_description = pc.describe_index(index_name)
                # Wait for index readiness
                max_wait_time = 60; wait_start = time.time()
                while not index_description.status['ready']:
                    if time.time() - wait_start > max_wait_time:
                         raise TimeoutError(f"Index '{index_name}' not ready after {max_wait_time}s.")
                    print("Index not ready, waiting 5s...")
                    time.sleep(5)
                    index_description = pc.describe_index(index_name)

                index_host = index_description.host
                CONFIG["pinecone_index_host"] = index_host # Update runtime config
                print(f"Discovered Pinecone index host: {index_host}")
            except PineconeException as e:
                print(f"ERROR: Pinecone API error during host discovery: {e}")
                raise
            except Exception as e:
                print(f"ERROR: Unexpected error during Pinecone host discovery: {e}")
                raise

        print(f"Connecting to Pinecone index '{index_name}' via host: {index_host}")
        pinecone_index = pc.Index(host=index_host)
        stats = pinecone_index.describe_index_stats()
        print(f"Pinecone Client and Index '{index_name}' Initialized. Stats: {stats}")
        return pc, pinecone_index

    except PineconeException as e:
        print(f"ERROR: Failed to initialize Pinecone client or index: {e}")
        raise
    except Exception as e:
        print(f"ERROR: Unexpected error initializing Pinecone: {e}")
        raise

PINECONE_CLIENT, PINECONE_INDEX = get_pinecone_client_and_index()

# --- Anthropic Client Setup ---
def get_anthropic_client():
    """Initializes and returns an Anthropic client."""
    api_key = CONFIG.get("anthropic_api_key")
    if not api_key:
        print("Warning: Anthropic API key not configured. Claude tool selection will not be available.")
        return None # Allow graceful failure
    try:
        client = Anthropic(api_key=api_key)
        print("Anthropic Client Initialized Successfully.")
        return client
    except AnthropicError as e:
        print(f"ERROR: Failed to initialize Anthropic client: {e}")
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error initializing Anthropic client: {e}")
        return None

ANTHROPIC_CLIENT = get_anthropic_client()

# --- Custom Logging Filter for MCP Handshake Warnings ---
import logging

class MCPHandshakeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """Filters out specific Pydantic validation warnings from MCP client handshake."""
        # Check if it's the Pydantic validation warning and related to 'sse/connection'
        # The logger name is 'root' based on the provided logs.
        is_mcp_warning = record.name == 'root' and record.levelname == 'WARNING'
        log_message = record.getMessage()
        is_validation_error_msg = "Failed to validate notification" in log_message
        is_sse_connection_related = "input_value='sse/connection'" in log_message
        
        if is_mcp_warning and is_validation_error_msg and is_sse_connection_related:
            # Suppress this specific log message
            # print(f"DEBUG: Suppressing MCP handshake warning: {log_message[:200]}...") # Optional: for debugging the filter
            return False
        return True

# Apply the filter to the root logger
# This ensures it's active for any warnings bubbling up to the root logger
# from the mcp library if it doesn't use a more specific logger for these warnings.
root_logger = logging.getLogger()
# Check if the filter is already added to prevent duplicates during reloads (e.g., with uvicorn --reload)
if not any(isinstance(f, MCPHandshakeFilter) for f in root_logger.filters):
    print("INFO: Applying MCPHandshakeFilter to root logger.")
    root_logger.addFilter(MCPHandshakeFilter())
else:
    print("INFO: MCPHandshakeFilter already applied to root logger.")

def generate_unique_video_id(url: str) -> str:
    """Generates a unique id based on the URL (TikTok format assumed)."""
    match = re.search(r"@(?P<username>[^/]+)/video/(?P<video_id>\d+)", url)
    if not match:
        print(f"Warning: Could not extract username/video_id from URL: {url}. Generating UUID-based name.")
        return str(uuid.uuid4())

    username = match.group("username")
    tiktok_video_id = match.group("video_id")
    video_id = f"{username}-{tiktok_video_id}"
    print(f"Generated video_id: {video_id} from URL: {url}")
    return video_id

VIDEO_DATA_PREFIX = "video-data/"

def get_s3_json_path(video_id: str) -> str:
    """Constructs the S3 key (path) for the video's JSON metadata file."""
    return f"{VIDEO_DATA_PREFIX}{video_id}/{video_id}.json"

def get_s3_interactions_path(video_id: str) -> str:
    """Constructs the S3 key (path) for the video's interactions.json file."""
    return f"{VIDEO_DATA_PREFIX}{video_id}/interactions.json"

def get_s3_video_base_path(video_id: str) -> str:
    """Constructs the base S3 key (path) for video/chunk files."""
    return f"{VIDEO_DATA_PREFIX}{video_id}/{video_id}" # e.g., video-data/video_id/video_id.mp4

# --- S3 JSON Read/Write Helpers (Crucial for State) ---

def get_video_metadata_from_s3(bucket: str, key: str) -> dict:
    """Reads the JSON metadata file from S3 and returns it as a dict."""
    try:
        response = S3_CLIENT.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        data = json.loads(content)
        print(f"Successfully read metadata from s3://{bucket}/{key}")
        return data
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print(f"S3 Key not found: s3://{bucket}/{key}")
            raise FileNotFoundError(f"Metadata file not found at {key}")
        else:
            print(f"Error reading from S3 s3://{bucket}/{key}: {e}")
            raise
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from s3://{bucket}/{key}: {e}")
        raise ValueError("Invalid JSON content in S3 file")
    except Exception as e:
        print(f"Unexpected error reading metadata from s3://{bucket}/{key}: {e}")
        raise

def get_interactions_from_s3(s3_bucket: str, s3_interactions_key: str) -> List[Dict[str, Any]]:
    """Fetches the list of interactions from the interactions JSON file in S3."""
    try:
        response = S3_CLIENT.get_object(Bucket=s3_bucket, Key=s3_interactions_key)
        content = response['Body'].read().decode('utf-8')
        interactions = json.loads(content)
        if not isinstance(interactions, list):
             print(f"Warning: Interactions data at {s3_interactions_key} is not a list. Returning empty.")
             return []
        # Validate structure slightly - ensure items are dicts (optional but good practice)
        # interactions = [item for item in interactions if isinstance(item, dict)]
        return interactions
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
             print(f"Interactions file not found at {s3_interactions_key}. Returning empty list.")
             return [] # Return empty list if file doesn't exist yet
        else:
            print(f"Error getting interactions from S3 ({s3_interactions_key}): {e}")
            raise # Re-raise other S3 errors
    except json.JSONDecodeError as e:
        print(f"Error decoding interactions JSON from S3 ({s3_interactions_key}): {e}")
        # Decide how to handle corrupted JSON, maybe return empty list or raise?
        # Returning empty might be safer for polling.
        return []
    except Exception as e:
        print(f"Unexpected error reading interactions from S3 ({s3_interactions_key}): {e}")
        # Consider logging the error more formally
        return [] # Return empty list on unexpected errors as well for polling robustness

def add_interaction_to_s3(s3_bucket: str, s3_interactions_key: str, new_interaction_data: Dict[str, Any]):
    """Adds a new interaction object to the interactions JSON file in S3."""
    # Read-modify-write with basic error handling for file existence/format.
    # WARNING: Potential race condition if multiple queries arrive near-simultaneously.
    try:
        # Fetch existing interactions, defaulting to an empty list if not found or invalid.
        interactions = get_interactions_from_s3(s3_bucket, s3_interactions_key)

        # Append the new interaction dictionary.
        # Ensure the passed 'new_interaction_data' contains all required fields like
        # 'interaction_id', 'user_name', 'user_query', 'query_timestamp', 'status'.
        interactions.append(new_interaction_data)

        # Write the updated list back to S3
        S3_CLIENT.put_object(
            Bucket=s3_bucket,
            Key=s3_interactions_key,
            Body=json.dumps(interactions, indent=2), # Use indent for readability
            ContentType='application/json'
        )
        print(f"Successfully added interaction {new_interaction_data.get('interaction_id')} to {s3_interactions_key}")

    except ClientError as e:
        # Catch S3 errors specifically during the put_object call
        print(f"S3 ClientError putting updated interactions to {s3_interactions_key}: {e}")
        raise # Re-raise S3 errors during write
    except Exception as e:
        # Catch other unexpected errors during the add process
        print(f"Unexpected error adding interaction to S3 ({s3_interactions_key}): {e}")
        raise

def update_interaction_status_in_s3(s3_bucket: str, s3_interactions_key: str, interaction_id: str, new_status: str, ai_answer: Optional[str] = None):
    """Updates status and optionally ai_answer for a specific interaction in S3."""
    # Read-modify-write logic.
    # WARNING: Potential race condition.
    try:
        # Fetch existing interactions. If file is invalid/not found, this will return [] or raise.
        interactions = get_interactions_from_s3(s3_bucket, s3_interactions_key)

        if not interactions:
             print(f"Warning: Interactions file {s3_interactions_key} is empty or missing. Cannot update status for {interaction_id}.")
             # If the file was missing, we can't update. If it was empty, the loop below won't run.
             # We might choose to raise an error here depending on expected behavior.
             # For now, just log and return, preventing the put_object call.
             return # Exit early

        # Find and update the interaction in the list
        interaction_found = False
        updated_interactions = [] # Build a new list to ensure clean data
        for interaction in interactions:
            # Check if it's a dictionary and the ID matches
            if isinstance(interaction, dict) and interaction.get('interaction_id') == interaction_id:
                # Create a copy to modify, preserving original fields
                updated_interaction = interaction.copy()
                updated_interaction['status'] = new_status
                updated_interaction['answer_timestamp'] = datetime.now(timezone.utc).isoformat()
                if ai_answer is not None:
                    updated_interaction['ai_answer'] = ai_answer
                updated_interactions.append(updated_interaction)
                interaction_found = True
                print(f"Prepared update for interaction {interaction_id} status to {new_status}.")
            elif isinstance(interaction, dict):
                # Keep other valid interactions
                updated_interactions.append(interaction)
            # else: skip invalid entries if any

        if not interaction_found:
            print(f"Warning: Interaction ID {interaction_id} not found in {s3_interactions_key}. No status update performed.")
            # No need to write back if nothing changed
            return

        # Write the updated list back to S3
        S3_CLIENT.put_object(
            Bucket=s3_bucket,
            Key=s3_interactions_key,
            Body=json.dumps(updated_interactions, indent=2),
            ContentType='application/json'
        )
        print(f"Successfully saved updated interactions to {s3_interactions_key} after status update for {interaction_id}.")

    except ClientError as e:
        print(f"S3 ClientError putting updated interactions (status update) to {s3_interactions_key}: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error updating interaction status in S3 ({s3_interactions_key}): {e}")
        raise

def update_overall_processing_status(bucket: str, key: str, overall_status: str):
    """Reads the S3 JSON, updates the top-level processing_status, writes it back."""
    print(f"Updating overall status for {key} to {overall_status}")
    retries = 3
    
    for attempt in range(retries):
        try:
            # 1. GET current JSON
            try:
                metadata = get_video_metadata_from_s3(bucket, key)
            except FileNotFoundError:
                # If file doesn't exist, create a minimal one
                metadata = {"processing_status": "PROCESSING"}
            
            # 2. Update status
            metadata["processing_status"] = overall_status
            
            # 3. PUT updated JSON back
            S3_CLIENT.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(metadata, indent=2),
                ContentType='application/json'
            )
            print(f"Successfully updated status to {overall_status} in s3://{bucket}/{key}")
            return  # Success, exit retry loop
            
        except ClientError as e:
            print(f"S3 ClientError on attempt {attempt + 1} updating status in {key}: {e}")
            if attempt == retries - 1: 
                raise  # Raise after last attempt
            time.sleep(2 ** attempt)  # Exponential backoff
            
        except Exception as e:
            print(f"Error updating status in {key} on attempt {attempt + 1}: {e}")
            if attempt == retries - 1: 
                raise  # Raise after last attempt
            time.sleep(2 ** attempt)  # Exponential backoff