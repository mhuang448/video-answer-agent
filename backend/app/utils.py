# app/utils.py
import os
import re
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from dotenv import load_dotenv
import uuid
import json # Added for MCP server config parsing
from typing import Optional, Dict, Any
import time # Added for Pinecone index readiness check
# Added imports for OpenAI and Pinecone
from openai import OpenAI, OpenAIError
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec
from pinecone.exceptions import PineconeException

# Added imports for MCP and Anthropic
# from mcp import ClientSession, StdioServerParameters # legacy import
# from mcp.client.stdio import stdio_client # legacy import
# from contextlib import AsyncExitStack # legacy import
# from mcp.client.session import ClientSession # legacy import
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

    # Commenting out legacy MCP server config loading from JSON file
    # Keep here for now for reference
    # # Load MCP server configurations from mcp_config.json
    # # Look for config in standard locations or specified path
    # mcp_config_path = os.getenv("MCP_CONFIG_PATH")
    # default_paths = [
    #     "app/mcp_config.json",
    #     os.path.expanduser("~/.config/mcp/config.json"), # Example Linux path
    #     os.path.expanduser("~/Library/Application Support/MCP/config.json") # Example macOS path
    # ]

    # # # FOR DEBUGGING:Print the current directory contents (simulate 'ls')
    # # try:
    # #     current_dir = os.getcwd()
    # #     print(f"Current directory: {current_dir}")
    # #     print("Directory contents:")
    # #     for item in os.listdir(current_dir):
    # #         item_path = os.path.join(current_dir, item)
    # #         if os.path.isdir(item_path):
    # #             print(f"  📁 {item}/")
    # #         else:
    # #             print(f"  📄 {item}")
    # # except Exception as e:
    # #     print(f"Error listing directory contents: {e}")

    # found_config_path = None
    # if mcp_config_path and os.path.exists(mcp_config_path):
    #     found_config_path = mcp_config_path
    # else:
    #     for path in default_paths:
    #         print(f"Checking for MCP config at: {path}")
    #         if os.path.exists(path):
    #             found_config_path = path
    #             break

    # if found_config_path:
    #     print(f"Loading MCP server configurations from: {found_config_path}")
    #     try:
    #         with open(found_config_path, 'r') as f:
    #             mcp_config_data = json.load(f)
    #             config["mcp_servers"] = mcp_config_data.get("mcpServers", {})
    #             print(f"Loaded {len(config['mcp_servers'])} MCP server configurations.")
    #     except json.JSONDecodeError as e:
    #         print(f"Warning: Error decoding JSON from {found_config_path}: {e}")
    #     except Exception as e:
    #         print(f"Warning: Failed to load MCP config from {found_config_path}: {e}")
    # else:
    #     print("Warning: No mcp_config.json found in default locations or specified by MCP_CONFIG_PATH.")

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
    # Anthropic key is optional if only using rule-based selection
    # if not config["anthropic_api_key"]:
    #     print("Warning: Missing ANTHROPIC_API_KEY environment variable (needed for Claude tool selection).")

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
        # Optional: Test call (might require specific permissions)
        # client.count_tokens(text="test")
        print("Anthropic Client Initialized Successfully.")
        return client
    except AnthropicError as e:
        print(f"ERROR: Failed to initialize Anthropic client: {e}")
        # Don't raise, as it's optional for now
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error initializing Anthropic client: {e}")
        return None

ANTHROPIC_CLIENT = get_anthropic_client()

# # --- MCP Helper Functions ---
# Commenting out legacy MCP server config loading from JSON file
# Keep here for now for reference

# def get_mcp_server_params(server_name: str) -> Optional[StdioServerParameters]:
#     """Gets StdioServerParameters for a named server from config."""
#     server_config = CONFIG.get("mcp_servers", {}).get(server_name)
#     if not server_config:
#         print(f"ERROR: MCP Server configuration '{server_name}' not found.")
#         return None

#     command = server_config.get("command")
#     args = server_config.get("args", [])
#     config_env_vars = server_config.get("env", {})

#     if not command:
#         print(f"ERROR: 'command' missing in MCP server config for '{server_name}'.")
#         return None

#     # Resolve environment variables, especially API keys like PERPLEXITY_API_KEY
#     processed_env = {}
#     for key, value in config_env_vars.items():
#         if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
#             env_var_name = value[2:-1]
#             env_value = CONFIG.get(env_var_name.lower()) # Match keys in our main CONFIG
#             if env_value:
#                 processed_env[key] = env_value
#             else:
#                 print(f"Warning: Could not resolve env var '{env_var_name}' for MCP server '{server_name}'.")
#                 # Keep original placeholder or set to empty string? Decide based on server needs.
#                 processed_env[key] = "" # Setting to empty might be safer
#         else:
#             processed_env[key] = value

#     # Special handling for Docker '-e' arguments if needed (similar to mcp_client.py)
#     if command == "docker" and "-e" in args:
#         new_args = []
#         i = 0
#         while i < len(args):
#             arg = args[i]
#             if arg == "-e" and i + 1 < len(args):
#                 env_key_in_arg = args[i+1]
#                 # Ensure this env key was resolved and added to processed_env
#                 if env_key_in_arg in processed_env:
#                     new_args.extend([arg, env_key_in_arg]) # Pass -e VAR_NAME
#                 else:
#                      print(f"Warning: Env var '{env_key_in_arg}' specified in Docker args for '{server_name}' but not found/resolved in config.")
#                      # Decide whether to skip or pass '-e VAR_NAME' anyway
#                      # Skipping might be safer if the key is mandatory
#                 i += 2 # Skip the key name
#             else:
#                 new_args.append(arg)
#                 i += 1
#         args = new_args
#         # Note: Docker daemon needs access to the resolved env vars passed via '-e'.
#         # The `processed_env` dict passed to StdioServerParameters is for the *mcp client process*,
#         # not necessarily the docker container directly unless command setup handles it.

#     return StdioServerParameters(command=command, args=args, env=processed_env)

# --- Standard Helper Functions ---

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
    return f"{VIDEO_DATA_PREFIX}{video_id}/{video_id}" # e.g., video-data/VID/VID.mp4

def determine_if_processed(video_name: str) -> bool:
    """Placeholder function to determine if a video is processed.
    In a real implementation, this might check for the existence of the file
    or review flags in a database.
    """
    # For PoC, we assume this is a newly processed video (not processed)
    # You could implement actual logic here if needed
    return False
