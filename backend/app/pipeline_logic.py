# app/pipeline_logic.py
import time
import json
import asyncio
from typing import List, Dict, Any
import concurrent.futures
import threading
import os # For environment variable based configuration for the job
from botocore.exceptions import ClientError # Already used by some S3 helpers in utils

# Import helper functions and clients from utils
from .utils import (
    S3_CLIENT, CONFIG,
    OPENAI_CLIENT, PINECONE_INDEX,
    ANTHROPIC_CLIENT,
    get_video_metadata_from_s3,
    add_interaction_to_s3,
    update_interaction_status_in_s3,
    VIDEO_DATA_PREFIX
)
from .models import VideoMetadata, Interaction # Import Pydantic models for structure

# Import specific exceptions for better handling
from openai import OpenAIError
from pinecone.exceptions import PineconeException

# Import FastMCP client and transport
from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import SSETransport

from mcp import ClientSession
from mcp.client.sse import sse_client

# Import Anthropic specific exceptions
from anthropic import APIError as AnthropicAPIError
# Import httpx exceptions for sse_client error handling
import httpx

S3_INTERACTIONS_FILENAME = "interactions.json"

def _retrieve_relevant_chunks(video_id: str, user_query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Embeds the user query and retrieves relevant chunks from Pinecone,
       filtering by video_id.
    """
    print(f"Retrieving relevant chunks for video '{video_id}', query: '{user_query}'")
    if not OPENAI_CLIENT:
        print("ERROR: OpenAI client not initialized. Cannot embed query.")
        raise RuntimeError("OpenAI client not available")
    if not PINECONE_INDEX:
        print("ERROR: Pinecone index not initialized. Cannot query index.")
        raise RuntimeError("Pinecone index not available")

    embed_model = CONFIG["openai_embedding_model"]
    
    # 1. Embed the query
    try:
        start_embed = time.time()
        response = OPENAI_CLIENT.embeddings.create(
            input=[user_query],
            model=embed_model
        )
        query_vector = response.data[0].embedding
        end_embed = time.time()
        print(f"DEBUG: Embedded query: {query_vector[:5]}...")
        print(f"  Query embedding took: {end_embed - start_embed:.4f} seconds")
    except OpenAIError as e:
        print(f"  ERROR embedding query: {e}")
        raise RuntimeError("Failed to embed query") from e
    except Exception as e:
        print(f"  Unexpected ERROR during query embedding: {e}")
        raise

    # 2. Query Pinecone with video_id filter
    try:
        start_query = time.time()
        filter_params = {"video_id": f"{video_id}"} # Pinecone expects metadata key directly
        print(f"  Filter params: {filter_params}")
        # Note: Pinecone metadata structure in index_and_retrieve.py used video_name. 
        # Note: the video_id for our backend is <USERNAME>-<VIDEO_ID> and the video_name is structured as <USERNAME>-<VIDEO_ID>.mp4 for Pinecone
        
        query_results = PINECONE_INDEX.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
            filter=filter_params 
        )
        end_query = time.time()
        print(f"  Pinecone query took: {end_query - start_query:.4f} seconds")

        retrieved_chunks = query_results.get('matches', [])
        print(f"  Retrieved {len(retrieved_chunks)} chunks for video '{video_id}'")
        
        # commenting out because we want to keep order of most semantically relevant chunks
        # # Sort by chunk_number
        # if retrieved_chunks:
        #     retrieved_chunks.sort(key=lambda x: x.get('metadata', {}).get('chunk_number', float('inf')))
        #     print("  Sorted retrieved chunks by chunk_number.")

        # log scores of retrieved chunks
        for i, chunk in enumerate(retrieved_chunks):
            print(f"Chunk {i+1} score: {chunk.get('score', 'N/A')}")

        return retrieved_chunks

    except PineconeException as e:
        print(f"  ERROR during Pinecone query: {e}")
        # Return empty list on Pinecone error to allow attempting context assembly
        return [] 
    except Exception as e:
        print(f"  Unexpected ERROR during Pinecone query: {e}")
        # Return empty list on general error
        return []

def _assemble_video_context(retrieved_chunks: List[Dict[str, Any]], video_metadata: Dict[str, Any]) -> str:
    """Assembles the context string from retrieved chunks and video metadata."""
    print("Assembling context...")
    
    # Extract details from the main video metadata
    video_summary = video_metadata.get("overall_summary", "No summary available.")
    video_id = video_metadata.get("video_id", "")
    # Extract TikTok user_name from video_id
    user_name = video_id.split('-')[0] if '-' in video_id else None
    key_themes = video_metadata.get("key_themes", "")
    total_duration = video_metadata.get("total_duration_seconds")
    num_chunks = video_metadata.get("num_chunks") # Might be None if not added during chunking
    num_chunks_suffix = f'/{num_chunks}' if isinstance(num_chunks, int) else ""

    context_parts = []
    context_parts.append("Video Summary:")
    context_parts.append(video_summary)

    # Add user_name to context
    if user_name:
        context_parts.append(f"\nUsername of TikTok account that posted this video:\n{user_name}")
    
    if key_themes:
        context_parts.append("\nKey Themes:")
        context_parts.append(key_themes)

    if total_duration:
        context_parts.append(f"\nTotal Video Duration: {total_duration:.2f} seconds")

    context_parts.append("\nPotentially Relevant Video Clips (in order from most to least relevant):")
    context_parts.append("---")

    if not retrieved_chunks:
        context_parts.append("(No specific video clips retrieved based on query)")
    else:
        for i, chunk_match in enumerate(retrieved_chunks):

            metadata = chunk_match.get('metadata', {})
            seq_num = metadata.get('chunk_number', '?')
            if isinstance(seq_num, (int, float)):
                seq_num = int(seq_num)
            start_ts = metadata.get('start_timestamp', '?') # Handle missing keys gracefully
            end_ts = metadata.get('end_timestamp', '?')
            caption = metadata.get('caption', '(Caption text missing)')

            # Calculate relative time hints
            norm_start = metadata.get('normalized_start_time')
            norm_end = metadata.get('normalized_end_time')
            time_hint = ""
            hints = []
            is_valid_start = isinstance(norm_start, (float, int))
            is_valid_end = isinstance(norm_end, (float, int))

            if is_valid_start and is_valid_end:
                if norm_start <= 0.15:
                    hints.append("near the beginning")
                if norm_end >= 0.85:
                    hints.append("near the end")
                if not hints and norm_start > 0.15 and norm_end < 0.85:
                    hints.append("around the middle")
            
            if hints:
                time_hint = f" ({' and '.join(hints)})"
            
            context_parts.append(f"Video Clip from {start_ts} to {end_ts} {time_hint}:")
            context_parts.append(caption)
            if i < len(retrieved_chunks) - 1:
                context_parts.append("---")

    video_context = "\n".join(context_parts)
    print(f"Video context assembly complete. Final video context length: {len(video_context)}")
    return video_context

def _assemble_intermediate_prompt(video_context: str, query: str) -> str:
    """Assembles the intermediate prompt for our MCP Client to send to the MCP server."""
    intermediate_prompt = f"""
**Context for Query Processing:**

A user is asking a question about a video. This video context details specific observations from the video—including described entities, actions, dialogue, sounds, visuals, and overall themes. The information in video context may useful to fully and best address the user query.

---

**User Query:**
{query}

---

**Video Context:**
{video_context}
---
""" 
    return intermediate_prompt

def _select_perplexity_tool_rule_based(query: str) -> str:
    """Selects the appropriate Perplexity tool based on the query content using heuristics."""
    query_lower = query.lower()
    research_keywords = [
        'research', 'analyze', 'study', 'investigate', 'comprehensive', 'detailed',
        'in-depth', 'thorough', 'scholarly', 'academic', 'compare', 'contrast',
        'literature', 'history of', 'development of', 'evidence', 'sources',
        'references', 'citations', 'papers'
    ]
    deep_research_keywords = ['Deep Research', 'DeepResearch']
    reasoning_keywords = [
        'why', 'how', 'how does', 'explain', 'reasoning', 'logic', 'analyze', 'solve',
        'problem', 'prove', 'calculate', 'evaluate', 'assess', 'implications',
        'consequences', 'effects of', 'causes of', 'steps to', 'method for',
        'approach to', 'strategy', 'solution'
    ]

    is_long_query = len(query.split()) > 50
    research_score = sum(1 for keyword in research_keywords if keyword in query_lower)
    deep_research_score = sum(1 for keyword in deep_research_keywords if keyword in query_lower)
    reasoning_score = sum(1 for keyword in reasoning_keywords if keyword in query_lower)

    if is_long_query: research_score += 1
    if query_lower.startswith(('why', 'how')) and len(query_lower.split()) > 5: reasoning_score += 1

    if deep_research_score >= 1 or research_score >= 3 or (research_score >= 2 and is_long_query):
        print("  Rule-based selection: perplexity_research")
        return "perplexity_research"
    elif reasoning_score >= 2:
        print("  Rule-based selection: perplexity_reason")
        return "perplexity_reason"
    else:
        print("  Rule-based selection: perplexity_ask (default)")
        return "perplexity_ask"

# LLM-based tool selection and execution logic
# Always use this to properly leverage Model Context Protocol
async def _select_and_run_tool_llm_based(
    client: FastMCPClient | ClientSession, # Changed from ClientSession
    query_context: str,
    anthropic_client: Any # Should be Anthropic client instance
) -> str:
    """Uses Claude to select an MCP tool, determine args, execute it via the FastMCP client, and return the text result."""
    if not anthropic_client:
        print("  ERROR: Anthropic client not available for LLM-based tool selection.")
        return "[Error: Anthropic client not configured]"

    tool_result_text = "[LLM did not select or run a tool]" # Default if no tool use happens

    try:
        # 1. Get available tools from the FastMCP client
        print("  Listing tools for LLM selection via FastMCP client...")
        list_response = await client.list_tools() # Use client object
        available_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in getattr(list_response, 'tools', [])
        ]
        if not available_tools:
            print("  Warning: No tools available from MCP server via FastMCP client.")
            return "[Error: No tools available from MCP server]"
        print(f"  Found tools: {[t['name'] for t in available_tools]}")

        # 2. Call Anthropic API
        messages = [{"role": "user", "content": query_context}]
        print("  Sending query and tools to Anthropic for selection...")
        claude_response = anthropic_client.messages.create(
            model=CONFIG["anthropic_tool_selection_model"],
            max_tokens=1000,
            messages=messages,
            tools=available_tools,
            tool_choice={"type": "any"}
        )

        # 3. Process Claude's response
        tool_called = False
        if claude_response.content:
            for content_block in claude_response.content:
                if content_block.type == 'tool_use':
                    tool_name = content_block.name
                    tool_args = content_block.input
                    print(f"  LLM selected tool: '{tool_name}' with args: {tool_args}")
                    tool_called = True

                    # 4. Execute the selected tool via FastMCP client
                    print(f"  Calling tool '{tool_name}' via FastMCP client...")
                    tool_call_start = time.time()
                    try:
                        tool_exec_result = await client.call_tool(tool_name, tool_args) # Use client object
                        tool_call_end = time.time()
                        print(f"  Tool call finished in {tool_call_end - tool_call_start:.2f} seconds.")

                        # 5. Extract text content (Parsing logic remains the same)
                        current_tool_text = ""
                        if hasattr(tool_exec_result, 'content') and tool_exec_result.content:
                            for part in tool_exec_result.content:
                                if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                    current_tool_text += part.text + "\n"
                            tool_result_text = current_tool_text.strip()
                            print(f"  Received text result from '{tool_name}' (length: {len(tool_result_text)} chars).")
                        elif hasattr(tool_exec_result, 'isError') and tool_exec_result.isError:
                             print(f"  WARN: Tool '{tool_name}' reported an error.")
                             for part in tool_exec_result.content:
                                 if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                     current_tool_text += part.text + "\n"
                             tool_result_text = f"[Tool Error: {current_tool_text.strip()}]"
                             print(f"  WARN: Extracted error message: {tool_result_text}")
                        else:
                            print(f"  Warning: Tool '{tool_name}' returned no content or unexpected structure.")
                            tool_result_text = f"[Tool '{tool_name}' returned no information]"

                    except Exception as e:
                        print(f"  ERROR calling tool '{tool_name}' via FastMCP client: {type(e).__name__} - {e}")
                        tool_result_text = f"[Error executing tool '{tool_name}': {e}]"

                    break # Exit loop after handling the first tool_use block
            
            if not tool_called:
                 print("  LLM did not request any tool calls.")
                 # Check if Claude provided a text response directly
                 for content_block in claude_response.content:
                     if content_block.type == 'text':
                         tool_result_text = content_block.text.strip()
                         print(f"  LLM provided direct text response (length: {len(tool_result_text)} chars).")
                         break # Use the first text block

    except AnthropicAPIError as ae:
        print(f"  ERROR: Anthropic API error during tool selection: {ae}")
        tool_result_text = f"[Error interacting with Anthropic API: {ae}]"
    except Exception as e:
        print(f"  ERROR: Unexpected error during LLM tool selection/execution: {e}")
        import traceback
        traceback.print_exc()
        tool_result_text = f"[Unexpected error during LLM-based tool process: {e}]"

    return tool_result_text

async def _call_fastmcp(
    intermediate_prompt: str,
    use_llm_selection: bool = True # Default set back to True
) -> str:
    """Connects to the configured MCP server URL via SSE/HTTP using FastMCP,
       selects and calls a tool (using LLM or rules), and returns the text result.
    """
    mcp_sse_url = CONFIG.get("mcp_perplexity_sse_url")
    if not mcp_sse_url:
        print("ERROR: MCP_PERPLEXITY_SSE_URL environment variable is not set.")
        return "[Error: MCP Server URL not configured]"

    # Ensure URL is well-formed
    if not mcp_sse_url.startswith(("http://", "https://")):
         print(f"ERROR: Invalid MCP_PERPLEXITY_SSE_URL format: {mcp_sse_url}. Expected http(s)://.../")
         return "[Error: Invalid MCP Server URL format]"
    if '/' not in mcp_sse_url.split('://', 1)[1]:
        mcp_sse_url = mcp_sse_url.rstrip('/') + '/sse'
        print(f"WARN: Assuming SSE endpoint is /sse. Full URL: {mcp_sse_url}")

    print(f"Connecting to MCP server via SSE at '{mcp_sse_url}' using FastMCP (LLM Select: {use_llm_selection})...")
    mcp_result_text = "[MCP call failed]"
    client = None

    try:
        print("  DEBUG: Creating SSETransport...")
        transport = SSETransport(mcp_sse_url)
        print(f"  DEBUG: Transport created for {mcp_sse_url}")

        print("  DEBUG: Creating FastMCPClient and connecting...")
        client = FastMCPClient(transport)
        async with client:
            print("  DEBUG: FastMCP client connected successfully within context manager.")

            # --- EDIT: Use LLM selection or Rule-based --- 
            if use_llm_selection:
                print("  DEBUG: Attempting LLM-based tool selection...")
                mcp_result_text = await _select_and_run_tool_llm_based(
                    client, # Pass the FastMCP client
                    intermediate_prompt,
                    ANTHROPIC_CLIENT
                )
            else:
                # Fallback to rule-based selection
                print("  DEBUG: Using rule-based tool selection...")
                selected_tool = _select_perplexity_tool_rule_based(intermediate_prompt)
                print(f"  DEBUG: Rule-based selected tool: '{selected_tool}'")
                print(f"  DEBUG: Calling tool '{selected_tool}' via FastMCP client...")
                tool_call_start = time.time()
                try:
                    tool_args = {"messages": [{"role": "user", "content": intermediate_prompt}]}
                    print(f"  DEBUG: Tool arguments: {json.dumps(tool_args)[:100]}...")
                    
                    result = await client.call_tool(selected_tool, tool_args)
                    tool_call_end = time.time()
                    print(f"  DEBUG: Raw tool result: {result}") 
                    print(f"  INFO: Tool call finished in {tool_call_end - tool_call_start:.2f} seconds.")

                    # --- Result Parsing (copied from previous working version) --- 
                    current_tool_text = ""
                    if hasattr(result, 'content') and isinstance(result.content, list):
                        print("  DEBUG: Extracting text from result.content list...")
                        for part in result.content:
                            if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                print(f"  DEBUG: Found text content part: {part.text[:50]}...")
                                current_tool_text += part.text + "\n"
                            else:
                                print(f"  DEBUG: Skipping non-text part: {part}")
                        mcp_result_text = current_tool_text.strip()
                        print(f"  INFO: Received text result from '{selected_tool}' (length: {len(mcp_result_text)} chars).")
                    elif isinstance(result, str):
                        print("  DEBUG: Result is likely a direct string.")
                        mcp_result_text = result
                        print(f"  INFO: Received simple string result from '{selected_tool}' (length: {len(mcp_result_text)} chars).")
                    elif hasattr(result, 'isError') and result.isError and hasattr(result, 'content') and isinstance(result.content, list):
                        print(f"  WARN: Tool '{selected_tool}' reported an error.")
                        for part in result.content:
                            if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                current_tool_text += part.text + "\n"
                        mcp_result_text = f"[Tool Error: {current_tool_text.strip()}]"
                        print(f"  WARN: Extracted error message: {mcp_result_text}")
                    else:
                        print(f"  WARN: Tool '{selected_tool}' returned unrecognized structure. Result: {result}")
                        mcp_result_text = f"[Tool '{selected_tool}' returned unexpected result structure]"
                    # --- End Result Parsing --- 

                except Exception as e:
                    print(f"  ERROR: Exception calling tool '{selected_tool}' (rule-based): {type(e).__name__} - {e}")
                    import traceback
                    traceback.print_exc()
                    mcp_result_text = f"[Error executing rule-based tool '{selected_tool}': {e}]"
            # --- END EDIT --- 

    except httpx.ConnectError as e: 
        print(f"  ERROR: Connection failed to MCP server at {mcp_sse_url}. Is it running? Details: {e}")
        mcp_result_text = f"[Error: Connection failed to MCP server at {mcp_sse_url}]"
    except httpx.HTTPStatusError as e: 
         print(f"  ERROR: HTTP error {e.response.status_code} from {mcp_sse_url}: {e.response.text}")
         mcp_result_text = f"[Error: HTTP {e.response.status_code} from MCP server]"
    except asyncio.TimeoutError: 
         print(f"  ERROR: Timeout during FastMCP interaction with {mcp_sse_url}.")
         mcp_result_text = "[Error: Timeout interacting with MCP server]"
    except Exception as e:
        print(f"  ERROR: Unexpected error during FastMCP interaction: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()
        mcp_result_text = f"[Unexpected error interacting with MCP server: {e}]"
    finally:
        print(f"INFO: FastMCP SSE interaction complete for server at '{mcp_sse_url}'.")

    return mcp_result_text

async def _call_mcp(
    intermediate_prompt: str,
    use_llm_selection: bool = True # Default set back to True
) -> str:
    """Connects to the configured MCP server URL via SSE/HTTP using FastMCP,
       selects and calls a tool (using LLM or rules), and returns the text result.
    """
    mcp_sse_url = CONFIG.get("mcp_perplexity_sse_url")
    if not mcp_sse_url:
        print("ERROR: MCP_PERPLEXITY_SSE_URL environment variable is not set.")
        return "[Error: MCP Server URL not configured]"

    # Ensure URL is well-formed
    if not mcp_sse_url.startswith(("http://", "https://")):
         print(f"ERROR: Invalid MCP_PERPLEXITY_SSE_URL format: {mcp_sse_url}. Expected http(s)://.../")
         return "[Error: Invalid MCP Server URL format]"
    if '/' not in mcp_sse_url.split('://', 1)[1]:
        mcp_sse_url = mcp_sse_url.rstrip('/') + '/sse'
        print(f"WARN: Assuming SSE endpoint is /sse. Full URL: {mcp_sse_url}")

    print(f"Connecting to MCP server via SSE at '{mcp_sse_url}' using FastMCP (LLM Select: {use_llm_selection})...")
    mcp_result_text = "[MCP call failed]"
    client = None

    try:
        async with sse_client(mcp_sse_url) as streams:
            read_stream, write_stream = streams
            print("  SSE client connection established, creating session object...")

            # Create a ClientSession using the streams from sse_client
            # NOTE: Using default clientInfo and capabilities as defined in mcp/client/session.py
            async with ClientSession(*streams) as client:
        # print("  DEBUG: Creating SSETransport...")
        # transport = SSETransport(mcp_sse_url)
        # print(f"  DEBUG: Transport created for {mcp_sse_url}")

        # print("  DEBUG: Creating FastMCPClient and connecting...")
        # client = FastMCPClient(transport)
        # async with client:
        #     print("  DEBUG: FastMCP client connected successfully within context manager.")

                # --- Use LLM selection or Rule-based --- 
                if use_llm_selection:
                    print("  DEBUG: Attempting LLM-based tool selection...")
                    mcp_result_text = await _select_and_run_tool_llm_based(
                        client, # Pass the FastMCP client
                        intermediate_prompt,
                        ANTHROPIC_CLIENT
                    )
                else:
                    # Fallback to rule-based selection
                    print("  DEBUG: Using rule-based tool selection...")
                    selected_tool = _select_perplexity_tool_rule_based(intermediate_prompt)
                    print(f"  DEBUG: Rule-based selected tool: '{selected_tool}'")
                    print(f"  DEBUG: Calling tool '{selected_tool}' via FastMCP client...")
                    tool_call_start = time.time()
                    try:
                        tool_args = {"messages": [{"role": "user", "content": intermediate_prompt}]}
                        print(f"  DEBUG: Tool arguments: {json.dumps(tool_args)[:100]}...")
                        
                        result = await client.call_tool(selected_tool, tool_args)
                        tool_call_end = time.time()
                        print(f"  DEBUG: Raw tool result: {result}") 
                        print(f"  INFO: Tool call finished in {tool_call_end - tool_call_start:.2f} seconds.")

                        # --- Result Parsing (copied from previous working version) --- 
                        current_tool_text = ""
                        if hasattr(result, 'content') and isinstance(result.content, list):
                            print("  DEBUG: Extracting text from result.content list...")
                            for part in result.content:
                                if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                    print(f"  DEBUG: Found text content part: {part.text[:50]}...")
                                    current_tool_text += part.text + "\n"
                                else:
                                    print(f"  DEBUG: Skipping non-text part: {part}")
                            mcp_result_text = current_tool_text.strip()
                            print(f"  INFO: Received text result from '{selected_tool}' (length: {len(mcp_result_text)} chars).")
                        elif isinstance(result, str):
                            print("  DEBUG: Result is likely a direct string.")
                            mcp_result_text = result
                            print(f"  INFO: Received simple string result from '{selected_tool}' (length: {len(mcp_result_text)} chars).")
                        elif hasattr(result, 'isError') and result.isError and hasattr(result, 'content') and isinstance(result.content, list):
                            print(f"  WARN: Tool '{selected_tool}' reported an error.")
                            for part in result.content:
                                if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                    current_tool_text += part.text + "\n"
                            mcp_result_text = f"[Tool Error: {current_tool_text.strip()}]"
                            print(f"  WARN: Extracted error message: {mcp_result_text}")
                        else:
                            print(f"  WARN: Tool '{selected_tool}' returned unrecognized structure. Result: {result}")
                            mcp_result_text = f"[Tool '{selected_tool}' returned unexpected result structure]"
                        # --- End Result Parsing --- 

                    except Exception as e:
                        print(f"  ERROR: Exception calling tool '{selected_tool}' (rule-based): {type(e).__name__} - {e}")
                        import traceback
                        traceback.print_exc()
                        mcp_result_text = f"[Error executing rule-based tool '{selected_tool}': {e}]"

    except httpx.ConnectError as e: 
        print(f"  ERROR: Connection failed to MCP server at {mcp_sse_url}. Is it running? Details: {e}")
        mcp_result_text = f"[Error: Connection failed to MCP server at {mcp_sse_url}]"
    except httpx.HTTPStatusError as e: 
         print(f"  ERROR: HTTP error {e.response.status_code} from {mcp_sse_url}: {e.response.text}")
         mcp_result_text = f"[Error: HTTP {e.response.status_code} from MCP server]"
    except asyncio.TimeoutError: 
         print(f"  ERROR: Timeout during FastMCP interaction with {mcp_sse_url}.")
         mcp_result_text = "[Error: Timeout interacting with MCP server]"
    except Exception as e:
        print(f"  ERROR: Unexpected error during FastMCP interaction: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()
        mcp_result_text = f"[Unexpected error interacting with MCP server: {e}]"
    finally:
        print(f"INFO: FastMCP SSE interaction complete for server at '{mcp_sse_url}'.")

    return mcp_result_text

def _synthesize_answer(user_query: str, video_context: str, mcp_result: str) -> str:
    """Synthesizes the final answer using OpenAI, combining the original query,
       video context, and the MCP result.
    """
    print("Synthesizing final answer using OpenAI...")
    if not OPENAI_CLIENT:
        print("ERROR: OpenAI client not initialized. Cannot synthesize answer.")
        return "[Error: OpenAI client not available for synthesis]"

    synthesis_model = CONFIG.get("openai_synthesis_model", "gpt-4o-mini")

    # Construct the prompt for the synthesis model
    prompt = f"""
**Task:**
Please answer the user query comprehensively by synthesizing relevant information from **both** the Video Context (details extracted directly from the video) and the relevant Internet Search Results provided below.

**Instructions:**
1.  Analyze the User Query embedded within the Video Context to understand the core question.
2.  Review the Video Context (summary, themes, specific segments) for information directly observable in the video.
3.  Review the Internet Search Results for broader context, facts, or related information.
4.  Formulate a cohesive answer that integrates relevant details from both sources.
5.  Prioritize information from the Video Context when the query pertains to specific events or details *within* the video itself.
6.  Use the Internet Search Results to enrich the answer, provide background, clarify concepts, or address aspects of the query not covered by the video context alone.
7.  If the combined information is insufficient to answer the query fully, state what information is available and what is missing. Do not speculate beyond the provided contexts.
8.  Generate the response in plain text only, without any markdown formatting.
9.  Do NOT include citations.
10.  You can optionally include timestamps or timestamp ranges WITHOUT milliseconds (only minutes and seconds) if they are helpful to the user. If you include timestamps, format them as "mm:ss" and timestamp ranges as "mm:ss-mm:ss".
11.  Provide a clear and concise answer.

---

**User Query:**
{user_query}

---

**Video Context (Includes User Query):**
{video_context}

---

**Internet Search Results:**
{mcp_result}

---

**Final Answer:**
"""
    # Debug: Print the synthesis prompt
    # print(f"DEBUG: Synthesis prompt: {prompt}")

    print(f"  Sending synthesis prompt to OpenAI model: {synthesis_model}")
    synthesis_start = time.time()
    try:
        completion = OPENAI_CLIENT.chat.completions.create(
            model=synthesis_model,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        final_answer = completion.choices[0].message.content
        synthesis_end = time.time()
        print(f"  OpenAI synthesis successful in {synthesis_end - synthesis_start:.2f} seconds.")
        return final_answer.strip() if final_answer else "[OpenAI returned an empty answer]"

    except OpenAIError as e:
        print(f"  ERROR during OpenAI synthesis: {e}")
        return f"[Error synthesizing answer using OpenAI: {e}]"
    except Exception as e:
        print(f"  Unexpected ERROR during OpenAI synthesis: {e}")
        return f"[Unexpected error during answer synthesis: {e}]"

def _delete_s3_object_sync(s3_client, bucket_name: str, s3_key: str) -> tuple[bool, str]:
    """
    Synchronously deletes a single object from S3.
    Designed to be called by the ThreadPoolExecutor.
    """
    thread_id = threading.get_ident()
    # Using print for logging as per existing style in this file
    print(f"[Thread-{thread_id}] Attempting to delete 's3://{bucket_name}/{s3_key}'...")
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
        print(f"[Thread-{thread_id}] SUCCESS: Deleted 's3://{bucket_name}/{s3_key}'")
        return True, s3_key
    except ClientError as e:
        print(f"[Thread-{thread_id}] ERROR deleting 's3://{bucket_name}/{s3_key}': {e}")
        return False, s3_key
    except Exception as e: # Catch any other unexpected errors
        print(f"[Thread-{thread_id}] UNEXPECTED ERROR deleting 's3://{bucket_name}/{s3_key}': {e}")
        return False, s3_key

def _find_interaction_files_in_s3(s3_client, bucket_name: str, base_prefix: str) -> List[str]:
    """
    Lists all interaction.json files in the S3 bucket under the specified base_prefix.
    Example base_prefix: "video-data/"
    """
    print(f"SCHEDULER_JOB: Scanning for '{S3_INTERACTIONS_FILENAME}' files under 's3://{bucket_name}/{base_prefix}'...")
    interaction_keys = []
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        # Paginate through common prefixes (representing video_id "directories")
        dir_iterator = paginator.paginate(Bucket=bucket_name, Prefix=base_prefix, Delimiter='/')

        for page in dir_iterator:
            if 'CommonPrefixes' in page:
                for prefix_obj in page['CommonPrefixes']:
                    video_id_level_prefix = prefix_obj.get('Prefix')
                    if video_id_level_prefix:
                        # Construct the full key for the interactions.json file
                        interaction_key = f"{video_id_level_prefix}{S3_INTERACTIONS_FILENAME}"
                        try:
                            # Check if the interactions.json file actually exists
                            s3_client.head_object(Bucket=bucket_name, Key=interaction_key)
                            interaction_keys.append(interaction_key)
                            print(f"SCHEDULER_JOB: Found for deletion: s3://{bucket_name}/{interaction_key}")
                        except ClientError as e:
                            # If file not found (NoSuchKey or 404), or forbidden (403), skip it
                            if e.response['Error']['Code'] in ('NoSuchKey', '404', '403'):
                                continue
                            else:
                                # Log other errors but continue scanning
                                print(f"SCHEDULER_JOB: Error checking S3 key '{interaction_key}': {e}")
        return interaction_keys
    except ClientError as e:
        print(f"SCHEDULER_JOB: S3 ClientError while listing objects in bucket '{bucket_name}' under prefix '{base_prefix}': {e}")
        return [] # Return empty list on error to prevent further processing
    except Exception as e:
        print(f"SCHEDULER_JOB: Unexpected error scanning S3 for '{S3_INTERACTIONS_FILENAME}' files: {e}")
        return []

def clear_all_interactions_job():
    """
    Job to find and delete all 'interactions.json' files from S3.
    This function is synchronous and designed to be run by APScheduler.
    """
    print("SCHEDULER_JOB: Starting daily job to clear all interactions.json files...")
    job_start_time = time.time()

    if not S3_CLIENT:
        print("SCHEDULER_JOB ERROR: S3_CLIENT not available. Cannot clear interactions.")
        return
    
    s3_bucket_name = CONFIG.get("s3_bucket_name")
    if not s3_bucket_name:
        print("SCHEDULER_JOB ERROR: S3_BUCKET_NAME not configured. Cannot clear interactions.")
        return

    # Use VIDEO_DATA_PREFIX from utils.py, ensuring it ends with '/'
    # This prefix is typically "video-data/"
    s3_target_prefix = VIDEO_DATA_PREFIX
    if not s3_target_prefix.endswith('/'):
        s3_target_prefix += '/'

    interaction_s3_keys = _find_interaction_files_in_s3(S3_CLIENT, s3_bucket_name, s3_target_prefix)

    if not interaction_s3_keys:
        print("SCHEDULER_JOB: No interaction.json files found to delete.")
        job_duration = time.time() - job_start_time
        print(f"SCHEDULER_JOB: Daily clear interactions job finished in {job_duration:.2f} seconds. 0 files processed.")
        return

    print(f"SCHEDULER_JOB: Found {len(interaction_s3_keys)} '{S3_INTERACTIONS_FILENAME}' files to delete.")

    # Configure max_workers for concurrent deletion, defaulting to 5
    # This can be tuned via an environment variable if needed.
    max_workers_env = os.getenv('CLEAR_INTERACTIONS_MAX_WORKERS', '5')
    try:
        max_workers = int(max_workers_env)
        if max_workers <= 0:
            max_workers = 5
            print(f"SCHEDULER_JOB WARN: CLEAR_INTERACTIONS_MAX_WORKERS must be positive, defaulting to {max_workers}.")
    except ValueError:
        max_workers = 5
        print(f"SCHEDULER_JOB WARN: Invalid CLEAR_INTERACTIONS_MAX_WORKERS value '{max_workers_env}', defaulting to {max_workers}.")

    success_count = 0
    failure_count = 0
    failed_s3_keys = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Map futures to S3 keys to identify them upon completion/failure
        future_to_s3_key = {
            executor.submit(_delete_s3_object_sync, S3_CLIENT, s3_bucket_name, s3_key): s3_key
            for s3_key in interaction_s3_keys
        }
        
        for future in concurrent.futures.as_completed(future_to_s3_key):
            s3_key_processed = future_to_s3_key[future]
            try:
                success, returned_s3_key = future.result()
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    failed_s3_keys.append(returned_s3_key)
            except Exception as exc:
                print(f"SCHEDULER_JOB EXCEPTION: Deleting key '{s3_key_processed}' generated an exception in the future: {exc}")
                failure_count += 1
                failed_s3_keys.append(s3_key_processed)

    job_duration = time.time() - job_start_time
    print("-" * 30)
    print("SCHEDULER_JOB: Daily clear interactions.json summary:")
    print(f"  Attempted to delete: {len(interaction_s3_keys)} files")
    print(f"  Successfully deleted: {success_count}")
    print(f"  Failed to delete: {failure_count}")
    if failed_s3_keys:
        print("  Failed S3 keys (see logs above for details):")
        for failed_key in failed_s3_keys:
            print(f"    - {failed_key}")
    print(f"  Job duration: {job_duration:.2f} seconds.")
    print("-" * 30)

async def run_query_pipeline_async(
    video_id: str,
    user_query: str,
    user_name: str,
    interaction_id: str,
    s3_json_path: str,
    s3_interactions_path: str,
    s3_bucket: str,
    interaction_data: Dict[str, Any]
):
    """Background task to answer a query for a PROCESSED video."""
    print(f"BACKGROUND TASK: Starting query pipeline for interaction {interaction_data.get('interaction_id')} by user '{user_name}' on video {video_id}")
    start_time = time.time()

    try:
        # 1. Add interaction using the provided data structure
        # This dictionary already has user_name, query, timestamps, and status='processing'
        add_interaction_to_s3(s3_bucket, s3_interactions_path, interaction_data)
        print(f"Added initial interaction record: {interaction_data}")

        # 2. Load full video metadata
        video_metadata = get_video_metadata_from_s3(s3_bucket, s3_json_path)
        print(f"===============\nVIDEO METADATA LOADED\n===============")

        # 3. Retrieve relevant chunks from Pinecone
        retrieved_chunks = _retrieve_relevant_chunks(video_id, user_query)
        print(f"===============\nRETRIEVED {len(retrieved_chunks)} CHUNKS\n===============")

        # 4. Assemble context (This now includes summary, themes, clips)
        video_context = _assemble_video_context(retrieved_chunks, video_metadata)
        intermediate_prompt = _assemble_intermediate_prompt(video_context, user_query)
        print(f"===============\nINTERMEDIATE PROMPT:\n{intermediate_prompt}\n===============")

        # 5. Call MCP tool (using the assembled context + query)
        print("DEBUG: Calling _call_mcp function...")
        # Use LLM selection by default as set in _call_mcp signature
        mcp_result = await _call_mcp(intermediate_prompt, use_llm_selection=True)
        print(f"===============\nMCP TOOL RESULT:\n{mcp_result}\n===============")

        # 6. Synthesize final answer (using the original context, MCP result, and query)
        final_answer = _synthesize_answer(user_query, video_context, mcp_result)
        print(f"===============\nFINAL ANSWER:\n{final_answer}\n===============")

        # 7. Update status to completed with the answer
        update_interaction_status_in_s3(
            s3_bucket, s3_interactions_path, interaction_id, "completed",
            ai_answer=final_answer
        )
        print(f"BACKGROUND TASK: Query pipeline for interaction {interaction_id} COMPLETED.")

    except Exception as e:
        print(f"BACKGROUND TASK ERROR: Query pipeline for interaction {interaction_id} FAILED: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        try:
            # Attempt to mark as failed
            update_interaction_status_in_s3(s3_bucket, s3_interactions_path, interaction_id, "failed")
        except Exception as update_e:
            print(f"BACKGROUND TASK ERROR: Failed to update status to failed for {interaction_id}: {update_e}")
    finally:
        end_time = time.time()
        print(f"BACKGROUND TASK: Query pipeline for interaction {interaction_id} finished in {end_time - start_time:.2f} seconds.")