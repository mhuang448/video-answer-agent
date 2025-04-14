# app/utils.py
import os
import random
import re
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from dotenv import load_dotenv
import uuid
from typing import Optional, Dict, Any
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