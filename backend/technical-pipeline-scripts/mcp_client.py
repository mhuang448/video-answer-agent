#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Client

This client implements the Model Context Protocol (MCP) - an open standard for integrating 
AI models with external tools and data sources.

MCP follows a client-server architecture where:
1. Clients (like this one) maintain connections with servers and process queries
2. Servers expose tools, resources, or capabilities
3. LLMs (like Claude) make decisions about which tools to use

Key concepts:
- Protocol lifecycle: initialize → list tools → call tools → cleanup
- Tools: executable functions exposed by servers that can be called by the client
- Standard I/O transport: communication via stdin/stdout

Reference: https://modelcontextprotocol.io/
"""

import os
import asyncio
import sys
import json
import logging
import time
from typing import Optional, List, Dict, Any, Union
from contextlib import AsyncExitStack
from openai import OpenAI

from dotenv import load_dotenv
from pathlib import Path

# Set up environment variables
dotenv_path = Path(".env.local")
load_dotenv(dotenv_path=dotenv_path)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_client")

# Check for required API keys
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    logger.warning("ANTHROPIC_API_KEY environment variable not found. Claude integration will be unavailable.")

PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
if not PERPLEXITY_API_KEY:
    logger.warning("PERPLEXITY_API_KEY environment variable not found. Perplexity integration will be unavailable.")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY environment variable not found. OpenAI integration will be unavailable.")

try:
    # Import MCP SDK components
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from anthropic import Anthropic
except ImportError as e:
    logger.error(f"Required package not found: {e}")
    print("Please install required packages with:")
    print("pip install mcp anthropic python-dotenv")
    sys.exit(1)

class ConfigManager:
    """
    Configuration manager for MCP client settings.
    
    This class centralizes config management and provides access to:
    1. Local config files (similar to Claude Desktop)
    2. Environment variables
    
    It simplifies server configuration and reuse by storing common server setups.
    """
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_path: Optional path to a local config file
        """
        self.config = {}
        
        # Load config from file if provided
        if config_path:
            self.load_config_file(config_path)
        else:
            # Try default locations
            default_paths = [
                "./mcp_config.json",
                os.path.expanduser("~/.mcp/config.json"),
                os.path.expanduser("~/Library/Application Support/MCP/config.json")
            ]
            
            for path in default_paths:
                if os.path.exists(path):
                    self.load_config_file(path)
                    break
    
    def load_config_file(self, path: str):
        """
        Load configuration from a JSON file.
        
        The config file format follows Claude Desktop's format with mcpServers:
        {
            "mcpServers": {
                "server-name": {
                    "command": "...",
                    "args": [...],
                    "env": {...}
                }
            }
        }
        
        Args:
            path: Path to the config file
        """
        try:
            with open(path, 'r') as f:
                self.config = json.load(f)
                logger.info(f"Loaded configuration from {path}")
        except Exception as e:
            logger.warning(f"Failed to load config from {path}: {str(e)}")
    
    def get_server_config(self, server_name: str) -> Dict[str, Any]:
        """
        Get configuration for a specific MCP server.
        
        Args:
            server_name: Name of the server configuration to retrieve
            
        Returns:
            Dictionary with server configuration or empty dict if not found
        """
        if not self.config or 'mcpServers' not in self.config:
            return {}
            
        servers = self.config.get('mcpServers', {})
        return servers.get(server_name, {})
    
    def list_servers(self) -> List[str]:
        """
        List all configured server names.
        
        Returns:
            List of server names from the configuration
        """
        if not self.config or 'mcpServers' not in self.config:
            return []
            
        return list(self.config.get('mcpServers', {}).keys())
    
    def get_secret(self, secret_name: str, default: str = None) -> str:
        """
        Get a secret from environment variables.
        
        Args:
            secret_name: Name of the secret (environment variable) to retrieve
            default: Default value if secret isn't found
            
        Returns:
            The secret value or default if not found
        """
        # Check environment variables
        env_value = os.environ.get(secret_name)
        if env_value:
            return env_value
            
        return default

class MCPClient:
    """
    A general-purpose MCP client that can connect to any MCP server.
    
    This client follows the MCP protocol to:
    1. Connect to MCP servers (Python, Node.js, or Docker-based)
    2. Discover available tools
    3. Process queries using an LLM (Claude)
    4. Execute tool calls and return responses
    
    The client is designed to be tool and provider agnostic, following
    the MCP architecture where a client can connect to multiple different
    server implementations.
    """
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the MCP client.
        
        Sets up session management and API clients but doesn't connect
        to any server yet. The AsyncExitStack enables proper resource
        cleanup with async context managers.
        
        Args:
            config_path: Optional path to a config file
        """
        self.session: Optional[ClientSession] = None
        # AsyncExitStack helps manage multiple asynchronous context managers (like the server connection)
        # ensuring they are all properly closed even if errors occur.
        self.exit_stack = AsyncExitStack()
        self.anthropic = None
        self.config_manager = ConfigManager(config_path)
        
        # Get Claude API key from ConfigManager, with fallback to environment variable
        anthropic_key = self.config_manager.get_secret("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
        if anthropic_key:
            # Initialize Anthropic client
            self.anthropic = Anthropic(api_key=anthropic_key)
            logger.info("Anthropic client initialized")
        else:
            logger.warning("Claude integration not available (missing API key)")

        self.openai = OpenAI(api_key=OPENAI_API_KEY)
        # system prompt for OpenAI 4o-mini to craft high quality responses given user query and MCP tool result
#         self.developer_prompt = """
# You are an AI assistant designed to craft concise, high-quality answers to User Queries in the minimum number of words necessary to comprehensively answer the User Query. You will receive two inputs:
# 1. User Query: The primary question or request from the user.
# 2. Additional Information: High-quality supplemental information from research or reports.

# Your task is to:
# - Provide a clear, concise, and precise answer to the User Query.
# - Leverage information from the Additional Information input only if it is directly relevant to effectively answering the User Query.
# - Do not include irrelevant or unnecessary details.
# - Do not include citations in your answer.
# - Always prioritize clarity, accuracy, and conciseness in your response.
# """
    
    async def connect(self, server_name: str, env_vars: Dict[str, str] = None):
        """
        Connect to a named MCP server from configuration.
        
        Args:
            server_name: Server name from config
            env_vars: Additional environment variables to pass to the server
            
        Returns:
            List of available tools from the server
            
        Raises:
            ValueError: If the server is not found in configuration
        """
        # Get server configuration
        server_config = self.config_manager.get_server_config(server_name)
        
        if not server_config:
            raise ValueError(f"Server '{server_name}' not found in configuration")
            
        logger.info(f"Connecting to named server: {server_name}")
        
        command = server_config.get("command")
        args = server_config.get("args", [])
        config_env_vars = server_config.get("env", {})
        
        # Merge any additional environment variables
        if env_vars:
            merged_env = {**config_env_vars, **env_vars}
        else:
            merged_env = config_env_vars
        
        # Process environment variables, replacing placeholders with actual values
        processed_env = {}
        
        # Handle docker run commands with -e flags in args (Perplexity style)
        if command == "docker" and "-e" in args:
            # Create a new args list to modify
            new_args = []
            
            # Process the args, looking for -e flags followed by env var names
            i = 0
            while i < len(args):
                arg = args[i]
                
                if arg == "-e" and i + 1 < len(args):
                    # Get the env var name that follows -e
                    env_var_name = args[i + 1]
                    
                    # Check if this env var is in the env section
                    if env_var_name in merged_env:
                        env_value = merged_env[env_var_name]
                        
                        # Handle environment variable references with ${VAR_NAME} syntax
                        if isinstance(env_value, str) and env_value.startswith("${") and env_value.endswith("}"):
                            # Extract the environment variable name
                            referenced_env_var = env_value[2:-1]
                            # Get the value from environment
                            resolved_value = self.config_manager.get_secret(referenced_env_var)
                            if resolved_value:
                                # Add the arg and env var to the new args
                                new_args.append(arg)  # -e
                                new_args.append(env_var_name)  # ENV_VAR_NAME
                                processed_env[env_var_name] = resolved_value
                            else:
                                logger.warning(f"Could not resolve env var {referenced_env_var} for {env_var_name}")
                                # Keep the original args but with empty value
                                new_args.append(arg)  # -e
                                new_args.append(env_var_name)  # ENV_VAR_NAME
                        else:
                            # Use the literal value
                            new_args.append(arg)  # -e
                            new_args.append(env_var_name)  # ENV_VAR_NAME
                            processed_env[env_var_name] = env_value
                    else:
                        # Env var not in env section, keep original args
                        new_args.append(arg)
                        if i + 1 < len(args):
                            new_args.append(args[i + 1])
                    
                    # Skip over the env var name
                    i += 2
                else:
                    # Not an env flag, keep as is
                    new_args.append(arg)
                    i += 1
            
            # Use the processed args
            args = new_args
        else:
            # For non-Docker commands, process env vars normally
            for key, value in merged_env.items():
                # Handle environment variable references with ${VAR_NAME} syntax
                if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                    # Extract the environment variable name
                    env_var_name = value[2:-1]
                    # Get the value from environment
                    env_value = self.config_manager.get_secret(env_var_name)
                    if env_value:
                        processed_env[key] = env_value
                    else:
                        # If not found, keep the placeholder for clarity
                        processed_env[key] = value
                        logger.warning(f"Could not resolve env var {env_var_name} for {key}")
                else:
                    processed_env[key] = value
        
        # Create server parameters
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=processed_env
        )
        
        logger.info(f"Connecting to MCP server...")
        
        # Connect to the server using the stdio_client helper, managed by the exit stack
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        # Create a ClientSession, also managed by the exit stack
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        # MCP Step 1: Initialize the connection with the server
        await self.session.initialize()
        
        # MCP Step 2: List available tools to verify connection and see capabilities
        response = await self.session.list_tools()
        tools = response.tools
        logger.info(f"Connected to server with tools: {[(f'Tool: {tool.name}', f'Description: {tool.description[:50]}...') for tool in tools]}")
        
        return tools
    
    async def process_query(self, query: str) -> str:
        """
        Process a query using Claude and available tools.
        
        This method:
        1. Gets the list of available tools from the server
        2. Sends the query to Claude with tool descriptions
        3. Executes any tool calls requested by Claude
        4. Sends results back to Claude for final response
        
        Args:
            query: The user's query string
            
        Returns:
            The final response text
        """
        if not self.session:
            raise ValueError("Not connected to any MCP server")
            
        if not self.anthropic:
            raise ValueError("Claude integration not available (missing API key)")
            
        # Start with the user's query
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]
        
        # Get available tools from the server
        # MCP Step 2 (again, can be called anytime after init): Get tool definitions for the LLM
        response = await self.session.list_tools()
        available_tools = [{
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]
        
        print("DEBUG: Available tools:")
        for tool in available_tools:
            print(f"DEBUG: - {tool['name']}: {tool['description'][:100]}...")
        
        # Initial Claude API call: Provide query and available tools
        print("Sending initial query and tool descriptions to Claude...")
        response = self.anthropic.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=1000,
            messages=messages,
            tools=available_tools,
            tool_choice={"type": "any"}
        )
        print(f"DEBUG: Claude initial response type: {[content.type for content in response.content]}")
        
        # Process response and handle tool calls if requested by Claude
        final_text = []
        
        assistant_message_content = [] # Accumulates parts of the assistant's turn (text and tool_use)
        for content in response.content:
            if content.type == 'text':
                # Part 1: Claude responds with text
                print(f"DEBUG: Claude responded with text: {content.text[:100]}...")
                final_text.append(content.text)
                assistant_message_content.append(content)
            elif content.type == 'tool_use':
                # Part 2: Claude requests a tool call
                tool_name = content.name
                tool_args = content.input
                
                print(f"DEBUG: Claude requested tool: {tool_name}")
                print(f"DEBUG: Tool arguments: {json.dumps(tool_args, indent=2)}")
                
                # MCP Step 3: Execute the requested tool call via the MCP server
                print(f"Calling {tool_name} via MCP server...")
                try:
                    result = await self.session.call_tool(tool_name, tool_args)
                    # Provide visual feedback that a tool was used
                    # final_text.append(f"[Used tool: {tool_name}]")
                    
                    print(f"DEBUG: Tool result received. Content type(s): {[getattr(part, 'type', 'unknown') for part in result.content]}")
                    # Extract and print text content from the result for clearer debugging
                    tool_result_text = ""
                    if result and result.content:
                        for part in result.content:
                            if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                                tool_result_text += part.text + "\n"
                    # Print the full tool result text without truncation
                    print(f"DEBUG: Tool result text content:\n{tool_result_text}") 
                    
                    # # Append the tool_use request to the assistant's message history
                    # assistant_message_content.append(content)
                    # # Add the complete assistant message (text + tool_use requests) to the conversation history
                    # messages.append({
                    #     "role": "assistant",
                    #     "content": assistant_message_content
                    # })
                    
                    # print("DEBUG: Updated messages history with assistant message")
                    
                    # # Add the tool result back into the conversation history for Claude
                    # messages.append({
                    #     "role": "user", # From the perspective of the LLM, tool results are provided by the "user" role
                    #     "content": [
                    #         {
                    #             "type": "tool_result",
                    #             "tool_use_id": content.id, # Link result to the specific tool request
                    #             "content": result.content  # The actual data returned by the tool via MCP
                    #         }
                    #     ]
                    # })
                    
                    # print("DEBUG: Added tool result to messages history")
                    
                    # # Get next response from Claude, providing the tool result context
                    # print("Sending tool results back to Claude for final response...")
                    # response = self.anthropic.messages.create(
                    #     model="claude-3-5-sonnet-20241022",
                    #     max_tokens=1000,
                    #     messages=messages,
                    #     tools=available_tools # Provide tools again in case Claude needs another
                    # )
                    
                    # print(f"DEBUG: Claude final response type: {[content.type for content in response.content]}")
                    
                    # # Append Claude's final text response (after considering the tool result)
                    # # Assuming the final response is primarily text after a tool call in this loop structure
                    # if response.content and response.content[0].type == 'text':
                    #      print(f"DEBUG: Claude's final text response: {response.content[0].text}")
                    #      final_text.append(response.content[0].text)
                    # else:
                    #      # Handle cases where Claude might request another tool immediately or give no text
                    #      print("Warning: Claude's response after tool call was not simple text.")
                    #      print(f"DEBUG: Unexpected response type: {[content.type for content in response.content]}")
                    #      # You might need more complex logic here to handle multi-turn tool calls


                except Exception as e:
                    error_msg = f"Error calling tool {tool_name} via MCP: {str(e)}"
                    print(error_msg)
                    print(f"DEBUG: Exception details: {repr(e)}")
                    final_text.append(f"[Error using tool {tool_name}]")
                    # Note: Error details are printed but not sent back to Claude in this flow.
                    # You might want to send an error message back to Claude in a production system.
                    # For example, appending a 'tool_result' message with an 'is_error=True' flag and error content.
                    break # Exit the loop for this query if a tool call fails

                print("Sending tool result to OpenAI 4o-mini for final response...")
                user_query = f"User Query:\n{query}\n\nAdditional Information:\n{tool_result_text}"
                developer_prompt = f"""
**Task:**
Please answer the user query comprehensively by synthesizing relevant information from **both** the Video Context (details extracted directly from the video) and the relevant Internet Search Results provided below.

**Instructions:**
1.  Analyze the User Query to understand the core question.
2.  Review the Video Context (summary, themes, specific segments) for information directly observable in the video.
3.  Review the Internet Search Results for broader context, facts, or related information.
4.  Formulate a cohesive answer that integrates relevant details from both sources.
5.  Prioritize information from the Video Context when the query pertains to specific events or details *within* the video itself.
6.  Use the Internet Search Results to enrich the answer, provide background, clarify concepts, or address aspects of the query not covered by the video context alone.
7.  If the combined information is insufficient to answer the query fully, state what information is available and what is missing. Do not speculate beyond the provided contexts.
8.  Do not include citations in your answer.
9.  Provide a clear and concise answer.

---

{query}

---

**Internet Search Results:**
{tool_result_text}

---

**Answer:**
"""
                print(f"DEBUG: Developer prompt:\n{developer_prompt}")
                # Use OpenAI to generate a response using the developer prompt and the tool result text
                try:
                    completion = self.openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                        {
                            # "role": "developer",
                            "role": "user",
                            # "content": self.developer_prompt
                            "content": developer_prompt
                        }
                    ]
                )

                    final_text.append(completion.choices[0].message.content)
                except Exception as e:
                    print(f"DEBUG: Exception in OpenAI gpt-4o-mini completion: {repr(e)}")
                    final_text.append(f"Sorry, seems like I'm having trouble answering that right now. Please try again later.")
        
        return "\n".join(final_text)
    
    def select_perplexity_tool(self, query: str) -> str:
        """
        Select the appropriate Perplexity tool based on the query content.
        
        This implements a rule-based approach to tool selection for Perplexity's tools.
        While MCP generally favors LLM-driven tool selection, rule-based selection
        can be appropriate in specific cases like:
        
        1. When no LLM is available for selection
        2. For specialized applications with clear selection criteria
        3. For performance optimization
        4. For deterministic behavior
        
        The three Perplexity tools are:
        - perplexity_ask: For simple, factual, or short queries
        - perplexity_research: For queries needing deep information or citations
        - perplexity_reason: For queries requiring analytical thinking or problem-solving
        
        Args:
            query: The user's query string
            
        Returns:
            The name of the selected Perplexity tool
        """
        query_lower = query.lower()
        
        # --- Define Keywords for Rule-Based Selection ---
        research_keywords = [
            'research', 'analyze', 'study', 'investigate', 'comprehensive', 'detailed',
            'in-depth', 'thorough', 'scholarly', 'academic', 'compare', 'contrast',
            'literature', 'history of', 'development of', 'evidence', 'sources',
            'references', 'citations', 'papers'
        ]

        deep_research_keywords = [
            'Deep Research', 'DeepResearch'
        ]

        reasoning_keywords = [
            'why', 'how', 'how does', 'explain', 'reasoning', 'logic', 'analyze', 'solve',
            'problem', 'prove', 'calculate', 'evaluate', 'assess', 'implications',
            'consequences', 'effects of', 'causes of', 'steps to', 'method for',
            'approach to', 'strategy', 'solution'
        ]

        # --- Apply Heuristics ---
        is_long_query = len(query.split()) > 50 # Threshold for considering a query "long".
        research_score = sum(1 for keyword in research_keywords if keyword in query_lower)
        deep_research_score = sum(1 for keyword in deep_research_keywords if keyword in query_lower)
        reasoning_score = sum(1 for keyword in reasoning_keywords if keyword in query_lower)
        
        if is_long_query: research_score += 1
        if query_lower.startswith(('why', 'how')) and len(query_lower.split()) > 5: reasoning_score += 1

        # --- Select Tool Based on Scores ---
        if deep_research_score >= 1 or research_score >= 3 or (research_score >= 2 and is_long_query):
            print(f"Selected 'perplexity_research' (Rule-based score: {research_score})")
            return "perplexity_research"
        elif reasoning_score >= 2:
            print(f"Selected 'perplexity_reason' (Rule-based score: {reasoning_score})")
            return "perplexity_reason"
        else:
            print(f"Selected 'perplexity_ask' (Default rule-based)")
            return "perplexity_ask"
            
    async def perplexity_query(self, query: str):
        """
        Send a query to Perplexity using rule-based tool selection.
        
        This method demonstrates an alternative to LLM-based tool selection
        by using heuristic rules to select the most appropriate Perplexity tool.
        It's useful when:
        1. You're specifically working with Perplexity tools
        2. You want consistent, deterministic tool selection
        3. You want to avoid the latency of LLM-based selection
        
        Args:
            query: The user's question
            
        Returns:
            The text response from Perplexity, or None if an error occurs
        """
        start_time = time.time()
        if not self.session:
            logger.error("Not connected to an MCP server")
            return None
            
        # Check available tools to see if we have Perplexity tools
        try:
            response = await self.session.list_tools()
            tools = response.tools
            perplexity_tools = [t for t in tools if t.name.startswith('perplexity_')]
            
            if not perplexity_tools:
                logger.error("No Perplexity tools found in the connected server")
                return None
                
            print(f"DEBUG: Found Perplexity tools: {[t.name for t in perplexity_tools]}")
            print(f"DEBUG: Tool descriptions:")
            for tool in perplexity_tools:
                print(f"DEBUG: - {tool.name}: {tool.description[:15]}...")
                
            logger.info(f"Found Perplexity tools: {[t.name for t in perplexity_tools]}")
        except Exception as e:
            logger.error(f"Error listing tools: {str(e)}")
            return None
            
        final_response = f"An unexpected error occurred in perplexity_query."
        try:
            logger.info(f"Sending query to Perplexity: '{query}'")
            print(f"DEBUG: Analyzing query for rule-based tool selection: '{query}'")
            
            # Select the appropriate tool based on query content
            selected_tool = self.select_perplexity_tool(query)
            print(f"DEBUG: Selected tool: {selected_tool}")
            
            # Call the selected Perplexity tool via MCP
            print(f"DEBUG: Calling {selected_tool} with query: '{query[:50]}...'")
            tool_call_start_time = time.time()
            result = await self.session.call_tool(
                selected_tool,
                {
                    "messages": [{"role": "user", "content": query}]
                }
            )
            tool_call_end_time = time.time()
            print(f"DEBUG: Received result from {selected_tool} in {tool_call_end_time - tool_call_start_time:.2f} seconds")
            
            # Extract text content from the tool result
            tool_result_text = ""
            if result and result.content:
                print(f"DEBUG: Tool result received. Content type(s): {[getattr(part, 'type', 'unknown') for part in result.content]}")
                for part in result.content:
                    if hasattr(part, 'type') and part.type == 'text' and hasattr(part, 'text'):
                        tool_result_text += part.text + "\n"
                tool_result_text = tool_result_text.strip()
            else:
                logger.warning(f"Tool: {selected_tool} returned no content.")
                tool_result_text = "" # Ensure it's an empty string if no content

            if not tool_result_text:
                # Handle case where tool returned no usable text
                 print(f"DEBUG: Tool {selected_tool} returned no text content.")
                 # Attempt OpenAI call without additional info
                 tool_result_text = "[Tool returned no information]"

            print(f"DEBUG: Extracted tool result text content (length: {len(tool_result_text)} chars):")
            print(f"{tool_result_text[:500]}...") # Keep truncation for this debug log
            
            # Use OpenAI to generate the final response based on the tool result
            print("Sending tool result to OpenAI 4o-mini for final response generation...")
            openai_start_time = time.time()
            user_prompt_for_openai = f"User Query:\n{query}\n\nAdditional Information:\n{tool_result_text}"
            try:
                completion = self.openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "developer", # Assuming 'developer' role works, adjust if needed
                            "content": self.developer_prompt
                        },
                        {
                            "role": "user",
                            "content": user_prompt_for_openai
                        }
                    ]
                )
                openai_end_time = time.time()
                final_response = completion.choices[0].message.content
                print(f"DEBUG: OpenAI completion successful in {openai_end_time - openai_start_time:.2f} seconds.")
                # Return is handled implicitly by setting final_response
                
            except Exception as e_openai:
                openai_end_time = time.time()
                print(f"DEBUG: Exception in OpenAI gpt-4o-mini completion after {openai_end_time - openai_start_time:.2f} seconds: {repr(e_openai)}")
                logger.error(f"Error during OpenAI completion: {str(e_openai)}")
                # Fallback: Return the raw tool result if OpenAI fails
                print("DEBUG: OpenAI failed. Falling back to raw tool result text.")
                final_response = tool_result_text # Use raw text as fallback response
            
        except Exception as e_mcp:
            # Catch errors during the MCP tool call itself
            selected_tool_name = selected_tool if 'selected_tool' in locals() else 'Unknown Tool'
            logger.error(f"Error calling Perplexity tool {selected_tool_name}: {str(e_mcp)}")
            print(f"DEBUG: Exception in perplexity_query during MCP call: {repr(e_mcp)}")
            final_response = f"Sorry, there was an error executing the {selected_tool_name} tool."
            # Return is handled implicitly by setting final_response

        finally:
            # This block executes regardless of exceptions or return paths in try/except
            end_time = time.time()
            print(f"DEBUG: Total time taken for perplexity_query: {end_time - start_time:.2f} seconds")
            return final_response # Return the determined response
        
    async def chat_loop(self, perplexity_mode: bool = False):
        """
        Run an interactive chat loop with tool-augmented responses.
        Respects the perplexity_mode flag to choose the query processing method.
        
        Args:
            perplexity_mode: If True, use rule-based tool selection (perplexity_query).
                             If False, use Claude-based tool selection (process_query).
        """
        if not self.session:
            logger.error("Not connected to an MCP server")
            return
            
        # Check if the required function is available based on mode
        if not perplexity_mode and not self.anthropic:
            logger.error("Claude integration not available (missing API key) for Claude-based selection mode.")
            print("Error: Claude integration is required for the default mode. Try --perplexity-mode or set ANTHROPIC_API_KEY.")
            return
        if perplexity_mode and not hasattr(self, 'perplexity_query'): # Basic check
             logger.error("Perplexity query function not available for perplexity-mode.")
             print("Error: Perplexity query function seems missing.")
             return
            
        logger.info("MCP Client Started!")
        print("\nMCP Client Started!")
        mode_string = "Rule-based Tool selection" if perplexity_mode else "Claude-based tool selection"
        print(f"Mode: {mode_string}")
        print("Type your queries or 'quit' to exit.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                
                if query.lower() in ['quit', 'exit', 'q', 'stop']:
                    break
                    
                logger.info(f"Processing query: {query}")
                print("Processing query...")
                
                if perplexity_mode:
                    response = await self.perplexity_query(query)
                else:
                    # We already checked self.anthropic exists if perplexity_mode is False
                    response = await self.process_query(query)
                    
                print("\n--- Response ---")
                print(response)
                print("----------------")
                
            except Exception as e:
                error_msg = f"Error during chat: {str(e)}"
                logger.error(error_msg)
                print(f"\nError: {str(e)}")
                
        logger.info("Chat session ended")
        
    async def cleanup(self):
        """
        Close all resources properly using the AsyncExitStack.
        
        This is MCP Step 4: Cleanup. Ensures the connection to the server
        is closed gracefully and any other managed resources are released.
        """
        logger.info("Cleaning up MCP client resources...")
        try:
            await self.exit_stack.aclose()
            logger.info("Cleanup complete.")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            print(f"Error during cleanup: {str(e)}")
        
async def main():
    """
    Main entry point demonstrating the MCP client usage.
    
    This script can be used with:
    python mcp_client.py <SERVER_NAME> [--query "Your query"] [--perplexity-mode] [--config path/to/config]
    
    Additional commands:
    - List configured servers: python mcp_client.py list-servers [config_path]
    """
    # Handle the list-servers command
    if len(sys.argv) > 1 and sys.argv[1] == "list-servers":
        config_path = sys.argv[2] if len(sys.argv) > 2 else None
        config = ConfigManager(config_path)
        servers = config.list_servers()
        
        if servers:
            print("Available configured servers:")
            for server in servers:
                print(f"  - {server}")
        else:
            print("No servers found in configuration.")
        return
        
    # Check if we have enough arguments
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python mcp_client.py <SERVER_NAME> [--query \"Your query\"] [--perplexity-mode] [--config path/to/config]")
        print("  python mcp_client.py list-servers [config_path]")
        sys.exit(1)
    
    # First argument is the server name
    server_name = sys.argv[1]
    
    # Parse flags
    query = None
    perplexity_mode = False
    config_path = None
    
    for i, arg in enumerate(sys.argv):
        if arg == "--query" and i+1 < len(sys.argv):
            query = sys.argv[i+1]
        elif arg == "--perplexity-mode":
            perplexity_mode = True
        elif arg == "--config" and i+1 < len(sys.argv):
            config_path = sys.argv[i+1]
    
    # Initialize the client with optional config path
    client = MCPClient(config_path)
    
    try:
        # Connect to the named server
        print(f"Connecting to server '{server_name}' from configuration...")
        try:
            await client.connect(server_name)
        except ValueError as e:
            print(f"Error: {str(e)}")
            print("Use 'python mcp_client.py list-servers' to see available servers.")
            sys.exit(1)
        
        # Handle query mode or interactive mode
        if query:
            print(f"\nSending query: '{query}'")
            query_start_time = time.time()
            if perplexity_mode:
                # Use rule-based Perplexity tool selection
                print("Using rule-based Perplexity tool selection")
                answer = await client.perplexity_query(query)
            elif client.anthropic:
                # Use Claude for tool selection
                print("Using Claude for tool selection")
                answer = await client.process_query(query)
            else:
                print("Claude integration not available. Cannot process query.")
                sys.exit(1)
            query_end_time = time.time()
            query_duration = query_end_time - query_start_time
            print(f"Query completed in {query_duration:.2f} seconds")
            if answer:
                print("\n--- Answer ---")
                print(answer)
                print("---------------\n")
            else:
                print("\nFailed to get an answer. Check logs for errors.")
        else:
            # Interactive chat mode - pass the mode flag
            await client.chat_loop(perplexity_mode)
            
    except Exception as e:
        print(f"An error occurred: {str(e)}")
    finally:
        # Ensure resources are cleaned up
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

# --- Setup and Usage Instructions ---
#
# This client implements the Model Context Protocol (MCP) and can connect to any
# MCP-compatible server defined in your configuration file.
#
# To use this client:
#
# 1. Set up your environment:
#    - Install dependencies: pip install mcp anthropic python-dotenv
#    - Create a .env.local file with your API keys
#       ANTHROPIC_API_KEY=your_key_here (for Claude integration)
#       Any other API keys needed by specific MCP servers
#
# 2. Create or update your mcp_config.json file:
#    - Start with the template: cp mcp_config.json.template mcp_config.json
#    - Add server configurations following the format in the template
#
# 3. Run the client:
#    python mcp_client.py <SERVER_NAME>
#    Example: python mcp_client.py perplexity-ask
#
#    Additional flags:
#       --query "Your query"     Send a one-time query
#       --perplexity-mode        Use rule-based tool selection for Perplexity
#       --config path/to/config  Use a custom config file
#
#    List available servers:
#       python mcp_client.py list-servers
#
# The client will:
# - Connect to the specified MCP server
# - List available tools
# - Process queries using Claude and the available tools
# - Return the responses
#