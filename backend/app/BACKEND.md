# Video Answer Agent (FastAPI RAG + MCP Service)

## Overview

## 1. Overview

This document describes the Python backend service for the Video Answer Agent project, built using the **FastAPI** framework.

**Purpose:** This backend acts as the central brain for the application. It handles requests from the frontend, manages the AI pipeline for answering questions about videos, interacts with external services (like AI models and databases), and stores/retrieves video data and user interactions.

**Key Features:**

- **Asynchronous Processing:** Uses FastAPI's `BackgroundTasks` to handle potentially time-consuming AI operations (like analyzing video context and calling external models) without making the user wait. The frontend receives an immediate acknowledgment, and results are fetched later.
- **RAG + MCP Pipeline:** Implements a sophisticated pipeline to answer user questions (`@AskAI <user_query>` comments):
  - **Retrieval-Augmented Generation (RAG):** Fetches relevant text segments (captions) from video data stored in a **Pinecone** vector database based on the user's query.
  - **Model Context Protocol (MCP):** Communicates with a separate **Perplexity MCP Server** (using the `FastMCP` library over HTTP/SSE) to leverage powerful search (`perplexity_ask`) and reasoning (`perplexity_reason`) tools. This enriches the context with real-time web information. Tool selection (ask vs. reason) is primarily handled by an **Anthropic (Claude)** model.
  - **Synthesis:** Uses an **OpenAI** model (e.g., `gpt-4o-mini`) to generate the final, coherent answer based on the user's query, retrieved video context, and MCP tool results.
- **State Management via S3:** Uses AWS S3 to store:
  - Video metadata (`<video_id>.json`): Contains processing status, summary, themes, etc.
  - User interactions (`interactions.json`): A list containing each question (`user_query`), status (`processing`, `completed`, `failed`), the AI answer (`ai_answer`), timestamps, and `user_name`. Stored separately to avoid conflicts during simultaneous updates.

## 2. Architecture & External Services

The backend relies on several external services and components:

1.  **AWS S3:**
    - **Storage:** Stores video metadata (`.json`) and interaction data (`.json`) under the `video-data/<video_id>/` prefix. _Note: Actual video file (.mp4) storage/processing is handled separately or assumed pre-existing for the scope of this backend API._
    - **State:** Acts as the primary data store for tracking video processing status and Q&A interactions.
2.  **Pinecone:**
    - **Vector Database:** Stores embeddings of video captions/chunks.
    - **Retrieval:** Enables finding relevant video segments based on semantic similarity of the video chunk's caption to the user's query. Accessed via the `pinecone-client[grpc]` library.
3.  **OpenAI API:**
    - **Embeddings:** Generates vector embeddings for user queries (e.g., using `text-embedding-ada-002`) to match against stored video captions in Pinecone.
    - **Synthesis:** Generates the final user-facing answer by combining context (e.g., using `gpt-4o-mini`).
4.  **Anthropic API:**
    - **Tool Selection:** Uses a Claude model (e.g., `claude-3-7-sonnet-20250219`) to intelligently choose the best Perplexity tool (`perplexity_ask` or `perplexity_reason`) exposed by the MCP server, based on the query and video context, and the tool's description. Accessed via the `anthropic` library.
5.  **Perplexity MCP Server:**
    - **External Service:** A _separate_ Node.js service (running in its own Docker container) exposing Perplexity API tools via the Model Context Protocol (MCP).
    - **Communication:** The FastAPI backend communicates with this server using the `fastmcp` client library over **HTTP/SSE** (Server-Sent Events) via a configured URL (`MCP_PERPLEXITY_SSE_URL`). This allows the backend to leverage Perplexity's search/reasoning capabilities.

## 3. Key Python Modules (`app/`)

- **`main.py`:**
  - **Role:** The main entry point. Defines the FastAPI application (`app`), configures **CORS** (Cross-Origin Resource Sharing) to allow requests from the frontend, and exposes the API endpoints.
  - **Functionality:** Handles incoming HTTP requests, validates request data using Pydantic models (from `models.py`), triggers background tasks for query processing (`run_query_pipeline_async`), and returns responses to the client. Includes a helper function (`get_processed_video_details`) to find videos marked "FINISHED" in S3 for the `/api/videos/foryou` endpoint.
- **`pipeline_logic.py`:**

  - **Role:** Contains the core business logic for the asynchronous AI query pipeline.
  - **Functionality:**
    - Orchestrates the RAG+MCP process triggered by `/api/query/async`.
    - **S3 State Management:** Includes functions to read (`get_video_metadata_from_s3`, `get_interactions_from_s3`) and write (`add_interaction_to_s3`, `update_interaction_status_in_s3`, `update_overall_processing_status`) state stored in S3 JSON files.
    - **RAG:** Implements `_retrieve_relevant_chunks` (embeds query via OpenAI, queries Pinecone) and `_assemble_video_context` (combines retrieved chunks with video summary/themes).
    - **MCP Interaction:** Implements `_call_mcp` which connects to the Perplexity MCP server using `FastMCPClient` and `SSETransport`. It primarily uses `_select_and_run_tool_llm_based` (calling Anthropic Claude) to determine the best Perplexity tool (`perplexity_ask` or `perplexity_reason`) and its arguments based on the query and video context (`intermediate_prompt`). It then executes the selected tool via the `FastMCPClient`. A rule-based fallback (`_select_perplexity_tool_rule_based`) exists but LLM selection is preferred.
    - **Synthesis:** Implements `_synthesize_answer` (calls OpenAI to generate the final answer).

- **`utils.py`:**
  - **Role:** Provides helper functions and shared client initializations.
  - **Functionality:**
    - `load_config`: Loads configuration from environment variables (e.g., API keys, S3 bucket name, `MCP_PERPLEXITY_SSE_URL`).
    - **Client Initialization:** Contains functions (`get_s3_client`, `get_openai_client`, `get_pinecone_client_and_index`, `get_anthropic_client`) to initialize and return ready-to-use clients for AWS S3, OpenAI, Pinecone, and Anthropic. These clients are initialized once when the module loads and stored in constants (e.g., `S3_CLIENT`, `OPENAI_CLIENT`). The Pinecone initialization includes logic to automatically discover the index host if not provided and waits for the index to be ready before returning.
    - `generate_unique_video_id`: Creates a standard `video_id` (e.g., `username-tiktokvideoid`) from a TikTok URL.
    - `get_s3_json_path`, `get_s3_interactions_path`: Helper functions to construct consistent S3 object keys.
- **`models.py`:**
  - **Role:** Defines data shapes using Pydantic models.
  - **Functionality:** Ensures data validation for API request bodies (e.g., `QueryRequest`) and response bodies (e.g., `VideoInfo`, `ProcessingStartedResponse`, `StatusResponse`). Also defines internal data structures like `Interaction` and `VideoMetadata` that mirror the format used in the S3 JSON files.

## 4. API Endpoints

These are the HTTP interfaces exposed by the FastAPI application (runs on port 8000 by default).

- **`GET /`**

  - **Tags:** `Health Check`
  - **Description:** A simple endpoint to verify if the backend service is running.
  - **Response:** `{"status": "ok", "message": "Welcome..."}`

- **`GET /api/videos/foryou`**

  - **Tags:** `Videos`
  - **Description:** Provides the frontend with a list of videos to display in the "For You" feed. It finds videos in S3 whose metadata (`<video_id>.json`) has `processing_status: "FINISHED"`, randomly selects up to 3, and returns their details including `video_id`, `like_count`, `uploader_name`, and a publicly accessible S3 URL for the video file (assuming the S3 bucket is configured for public reads of .mp4 files).
  - **Response Model:** `List[VideoInfo]`

- **`POST /api/query/async`**

  - **Tags:** `Query`
  - **Status Code:** `202 Accepted` (Indicates the request was accepted for processing, but is not yet complete).
  - **Description:** This is the main endpoint for asking questions about **already processed** videos.
    - Receives the `video_id`, the `user_query`, and the `user_name`.
    - Immediately creates a unique `interaction_id` and records the new interaction (with status `processing`) in the video's `interactions.json` file on S3.
    - **Triggers the asynchronous `run_query_pipeline_async` background task** (defined in `pipeline_logic.py`) to perform the full RAG+MCP+Synthesis flow.
    - Returns an immediate response confirming the processing has started.
  - **Request Body Model:** `QueryRequest` (`video_id`, `user_query`, `user_name`)
  - **Response Model:** `ProcessingStartedResponse` (`status`, `video_id`, `interaction_id`)

- **`GET /api/query/status/{video_id}`**

  - **Tags:** `Query`
  - **Description:** Allows the frontend to **poll** (check periodically) for the status of a video and its associated Q&A interactions.
    - Reads the main `<video_id>.json` file from S3 to get the overall `processing_status`, `like_count`, and `uploader_name`.
    - Reads the `interactions.json` file from S3 to get the list of all questions and their current `status` (`processing`, `completed`, `failed`) and `ai_answer` (if completed).
    - Returns this combined information to the frontend.
  - **Path Parameter:** `video_id` (string, e.g., `username-tiktokvideoid`)
  - **Response Model:** `StatusResponse` (`processing_status`, `video_url`, `like_count`, `uploader_name`, `interactions: List[Interaction]`)

## 5. Query Answer Generation Flow

When a user asks `@AskAI ...` via `POST /api/query/async`:

1.  **`main.py`:** Receives request -> Creates `interaction_id` -> Adds initial interaction record to S3 `interactions.json` (status: `processing`) -> Starts background task (`run_query_pipeline_async`).
2.  **`run_query_pipeline_async` (Background Task):**
    a. **Load Metadata:** Reads video summary/themes from S3 `<video_id>.json`.
    b. **RAG - Retrieve (`_retrieve_relevant_chunks`):**
    _ Embeds `user_query` (OpenAI Embedding Model).
    _ Queries Pinecone index (filtering by `video_id`) -> Gets relevant caption chunks.
    c. **RAG - Context (`_assemble_video_context`):** Combines video summary, themes, and retrieved caption chunks into `video_context`.
    d. **Prepare MCP Input (`_assemble_intermediate_prompt`):** Creates prompt including `user_query` and `video_context`.
    e. **MCP Call (`_call_mcp` using `_select_and_run_tool_llm_based`):**
    _ Connects to Perplexity MCP Server (FastMCP/SSE).
    _ Sends prompt & available tools list to Anthropic Claude.
    _ Claude selects tool (`perplexity_ask` or `perplexity_reason`) and arguments.
    _ Backend calls tool via FastMCP -> Gets `mcp_result` from Perplexity MCP Server (web search/reasoning info).
    f. **Synthesize (`_synthesize_answer`):**
    _ Sends `user_query`, `video_context`, and `mcp_result` to OpenAI (`gpt-4o-mini`).
    _ Gets `final_answer`.
    g. **Update State:** Updates the interaction record in S3 `interactions.json` (status: `completed`, adds `ai_answer`).
3.  **`GET /api/query/status/{video_id}` (Polling):**
    - Frontend calls this periodically.
    - `main.py` reads S3 `<video_id>.json` and `interactions.json`.
    - Returns current status and all interactions (including the now `completed` one with the `ai_answer`).

## 6. Configuration (Environment Variables)

The backend relies heavily on environment variables for configuration. Use a `.env` file for local development (loaded by `python-dotenv` in `utils.py`). In production (e.g., AWS App Runner), set these directly in the service configuration.

**Essential Variables:**

- `AWS_REGION`: AWS region for S3 (e.g., `us-east-1`).
- `S3_BUCKET_NAME`: Name of the S3 bucket for metadata/interactions.
- `PINECONE_API_KEY`: API key for your Pinecone account.
- `PINECONE_INDEX_NAME`: Name of the Pinecone index storing video caption embeddings.
- `OPENAI_API_KEY`: API key for your OpenAI account.
- `PERPLEXITY_API_KEY`: API key for Perplexity. _(Required by the separate Perplexity MCP Server container, not directly by this backend container, but crucial for the overall system)._
- `ANTHROPIC_API_KEY`: API key for Anthropic (needed for Claude-based tool selection).
- `MCP_PERPLEXITY_SSE_URL`: **Crucial.** The full URL (e.g., `http://mcp-server:8080/sse` or `https://<your-mcp-server-url>/sse`) where the Perplexity MCP Server's SSE endpoint is listening. The backend _must_ be able to reach this URL.
- _(Optional but Recommended for Production)_: AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) if **not** using IAM roles (e.g., an App Runner Instance Role, which is the preferred method).

**Optional Variables:**

- `PINECONE_INDEX_HOST`: Explicit host for the Pinecone index. If not provided, `utils.py` will try to discover it using the Pinecone API.
- `OPENAI_EMBEDDING_MODEL`: OpenAI model for embeddings (defaults to `text-embedding-ada-002`).
- `OPENAI_SYNTHESIS_MODEL`: OpenAI model for answer synthesis (defaults to `gpt-4o-mini`).
- `ANTHROPIC_TOOL_SELECTION_MODEL`: Anthropic model for MCP tool selection (defaults to `claude-3-7-sonnet-20250219`).

## 7 Running and developing locally

from `/backend` directory, run `uvicorn app.main:app --reload`

## 8. Running with Docker

(Assumes Docker and Docker Compose are installed)

1.  **Prerequisites:** Ensure you have Docker and Docker Compose installed.
2.  **Clone Repository:** Make sure you have the entire project code.
3.  **`.env` File:** Create a `.env` file in the **project root directory** (e.g., outside the `backend` folder if using the provided `docker-compose.yml`). Populate it with **all** required environment variables listed above (AWS, Pinecone, OpenAI, Perplexity, Anthropic, MCP Server URL). _Remember: `MCP_PERPLEXITY_SSE_URL` for local Docker Compose is typically `http://mcp-server:8080/sse`._ **Do not commit this file to Git.**
4.  **Build Docker Images:** Open a terminal in the project root directory and run:
    ```bash
    docker compose build
    ```
5.  **Run Services:** Start the backend and the Perplexity MCP server containers:
    ```bash
    docker compose up
    ```
    - The FastAPI backend should become available at `http://localhost:8000`.
    - The Perplexity MCP server should be running (likely on port 8080 inside Docker, accessible via the name `mcp-server` from the backend container).
6.  **Testing:**
    - Access the health check: `http://localhost:8000/` in your browser.
    - Access the OpenAPI docs: `http://localhost:8000/docs`.
    - Use tools like `curl`, Postman, or the frontend application (if running) to send requests to the API endpoints (e.g., `POST` to `http://localhost:8000/api/query/async`).
    - Monitor logs: `docker compose logs -f backend` and `docker compose logs -f mcp-server`.
7.  **Shutdown:** Press `Ctrl+C` in the terminal where `docker compose up` is running, then run:
    ```bash
    docker compose down
    ```

## 9. Deployment (Example: AWS App Runner)

1.  **Dockerfile (`backend/Dockerfile`):** This file defines how to build the container image. It uses a Python base image, installs dependencies from `requirements.txt`, copies the `app` code, exposes port 8000, and sets the command to run `uvicorn`.
2.  **Build & Push Image:** Build the Docker image and push it to a container registry like AWS ECR.

    ```bash
    # Authenticate Docker with ECR (replace placeholders)
    aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-account-id>.dkr.ecr.<your-region>.amazonaws.com

    # Build the image (run from the project root or adjust path to backend)
    docker build -t video-backend ./backend

    # Tag the image for ECR
    docker tag video-backend:latest <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/video-backend:latest

    # Push the image
    docker push <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/video-backend:latest
    ```

3.  **Deploy Perplexity MCP Server:** Deploy the separate Perplexity MCP server (using its own Dockerfile and App Runner service configuration) first. Note its public URL.
4.  **Deploy Backend Service (App Runner):**
    - Create a new AWS App Runner service.
    - **Source:** Choose "Container registry" and provide the ECR image URI pushed in step 2.
    - **Port:** Configure the service port to `8000`.
    - **Environment Variables:** Add **all** required environment variables from Section 6. **Crucially**, set `MCP_PERPLEXITY_SSE_URL` to the public URL of the **deployed Perplexity MCP server** (from step 3), including the `/sse` path.
    - **Instance Role (Recommended):** Create and assign an IAM role with permissions to access the S3 bucket (`s3:GetObject`, `s3:PutObject`, `s3:ListBucket` for the relevant paths) and potentially `pinecone:DescribeIndex` if host discovery is needed. This is more secure than using access keys.
    - **Health Check:** Configure an HTTP health check for the `/` path on port `8000`.
5.  **Deployment:** App Runner will pull the image, provision resources, and deploy the service, providing a public URL for your backend API.

## 10. Key Dependencies (`requirements.txt`)

- `fastapi`: The web framework.
- `uvicorn[standard]`: The ASGI server to run FastAPI.
- `pydantic`: For data validation and settings management.
- `boto3`: AWS SDK for Python (interacting with S3).
- `openai`: Official OpenAI Python client library.
- `pinecone-client[grpc]`: Official Pinecone client library (using gRPC).
- `fastmcp`: Client library for the FastMCP protocol variant (communicating with the Perplexity MCP Server).
- `httpx`, `httpx-sse`: Asynchronous HTTP client libraries (required by `fastmcp` for SSE).
- `anthropic`: Official Anthropic Python client library (for Claude tool selection).
- `python-dotenv`: Loads `.env` files for local development.
- `google-genai`: Google AI client library (likely intended for captioning, though captioning logic is currently a placeholder).
- _(Placeholder-related):_ `yt_dlp`, `moviepy`, `TikTokApi`, `scenedetect`, `opencv-python` are listed but the corresponding logic in `pipeline_logic.py` is not active.
