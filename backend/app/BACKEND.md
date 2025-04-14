# Video Q&A AI Agent - Python Backend

## Overview

This FastAPI application serves as the core backend for the Video Q&A AI Agent. It orchestrates the entire process, from receiving video URLs or queries about existing videos, managing the processing pipeline, interacting with external AI services and data stores, and providing status updates and results to the frontend.

The backend is designed to be asynchronous, leveraging FastAPI's background tasks to handle potentially long-running video processing and AI operations without blocking API responses.

## Architecture

The backend interacts with several key components:

1.  **AWS S3:** Used for storing raw video files (MP4 format), processed video chunks (currently placeholder logic), and JSON metadata files (`<video_id>.json`, `interactions.json`) that track the state of video processing and user queries.
2.  **Pinecone:** A vector database (using gRPC client `pinecone-client[grpc]`) used to store and index video caption embeddings, enabling efficient retrieval of relevant video segments based on user queries.
3.  **OpenAI API:** Used for generating embeddings (e.g., `text-embedding-ada-002`) for video captions and user queries, and for synthesizing the final answer (e.g., `gpt-4o-mini`) based on retrieved context and external search results.
4.  **Anthropic API:** Used for LLM-based tool selection using models like `claude-3-7-sonnet-20250219` if LLM-based tool selection is enabled in `pipeline_logic.py`. The `anthropic` library is used for this.
5.  **Perplexity MCP Server:** A separate Node.js service (documented in `backend/perplexity-mcp-server/PERPLEXITY_MCP_SERVER.md` and running in its own Docker container) that exposes Perplexity's search capabilities (`perplexity_ask`, `perplexity_reason`) via the **FastMCP** protocol over **HTTP/SSE**. The backend communicates with this server using the `fastmcp` client library and `httpx-sse` to enrich answers with real-time web information.

## Key Modules

- **`app/main.py`:** Defines the FastAPI application instance (`app`), sets up CORS middleware (allowing configurable origins, defaults to `http://localhost:3000`), and exposes the API endpoints. It handles incoming requests, validates them using Pydantic models (from `app/models.py`), and schedules background tasks (`run_query_pipeline_async`, `run_full_pipeline_async`) for processing. Includes a helper `get_list_of_processed_video_ids` to find finished videos in S3 for the `/foryou` endpoint.
- **`app/pipeline_logic.py`:** Contains the core business logic for both the full video processing pipeline (download, chunking, captioning, indexing - **currently placeholder functions** `_download_video`, `_chunk_video`, `_generate_captions_and_summary`, `_index_captions`) and the query pipeline (retrieval, context assembly, MCP interaction, answer synthesis). It interacts with all external services (S3, Pinecone, OpenAI, MCP Server via FastMCP). Includes functions for managing state in S3 JSON files (`get_video_metadata_from_s3`, `get_interactions_from_s3`, `add_interaction_to_s3`, `update_interaction_status_in_s3`, `update_overall_processing_status`). The query pipeline performs retrieval (`_retrieve_relevant_chunks`), context assembly (`_assemble_video_context`, `_assemble_intermediate_prompt`), calls the MCP server (`_call_mcp` using `fastmcp.Client` and `SSETransport`), and synthesizes the final answer (`_synthesize_answer`). `_call_mcp` supports both LLM-based tool selection (via `_select_and_run_tool_llm_based` using Anthropic) and rule-based selection (`_select_perplexity_tool_rule_based`).
- **`app/utils.py`:** Provides utility functions for:
  - Loading configuration from environment variables (`load_config`, stored in `CONFIG`). **Crucially, it now loads `MCP_PERPLEXITY_SSE_URL` instead of relying on a JSON config file for MCP.**
  - Initializing clients for external services: AWS S3 (`get_s3_client`, `S3_CLIENT`), OpenAI (`get_openai_client`, `OPENAI_CLIENT`), Pinecone (`get_pinecone_client_and_index`, `PINECONE_CLIENT`, `PINECONE_INDEX`), and Anthropic (`get_anthropic_client`, `ANTHROPIC_CLIENT`). Pinecone client initialization includes logic to discover the index host if not provided via `PINECONE_INDEX_HOST` and waits for index readiness.
  - Generating unique video IDs from TikTok URLs (`generate_unique_video_id`).
  - Constructing S3 paths (`get_s3_json_path`, `get_s3_interactions_path`, `get_s3_video_base_path`).
- **`app/models.py`:** Defines Pydantic models (`QueryRequest`, `ProcessRequest`, `VideoInfo`, `ProcessingStartedResponse`, `StatusResponse`, `VideoMetadata`, `Interaction`, etc.) used for request/response validation and data structuring within the API endpoints and pipeline logic.

## API Endpoints

The following endpoints are exposed by the FastAPI application (running on port 8000 by default, as defined in `Dockerfile` and `CMD`):

- **`GET /`** (Tags: `Health Check`)

  - **Description:** Basic health check.
  - **Response:** `{"status": "ok", "message": "Welcome..."}`

- **`GET /api/videos/foryou`** (Tags: `Videos`)

  - **Description:** Returns a list of up to 3 randomly selected video IDs that have a `"FINISHED"` status in their S3 metadata JSON file, along with their public S3 URLs (constructed assuming public read access). Uses the `get_list_of_processed_video_ids` helper.
  - **Response Model:** `List[VideoInfo]` (List of objects with `video_id` and `video_url`)

- **`POST /api/query/async`** (Status Code: 202 Accepted, Tags: `Query`)

  - **Description:** Accepts a query about an **already processed** video. Triggers an asynchronous background task (`run_query_pipeline_async`) to retrieve relevant context from Pinecone, call the Perplexity MCP Server (via FastMCP/SSE) for web search/reasoning, synthesize an answer using OpenAI, and update the status in the `interactions.json` file in S3.
  - **Request Body Model:** `QueryRequest` (`video_id`, `user_query`)
  - **Response Model:** `ProcessingStartedResponse` (`status`, `video_id`, `interaction_id`)

- **`POST /api/process_and_query/async`** (Status Code: 202 Accepted, Tags: `Query`)

  - **Description:** Accepts a new video URL (assumed TikTok format) and an initial query. Triggers an asynchronous background task (`run_full_pipeline_async`) to perform the **full processing pipeline** (download, chunk, caption, index - **currently placeholders**) followed by the query pipeline (retrieve, MCP call, synthesize). Creates initial metadata and interaction files in S3.
  - **Request Body Model:** `ProcessRequest` (`video_url`, `user_query`)
  - **Response Model:** `ProcessingStartedResponse` (`status`, `video_id`, `interaction_id`)

- **`GET /api/query/status/{video_id}`** (Tags: `Query`)

  - **Description:** Pollable endpoint to check the overall processing status of a video (from `<video_id>.json`) and retrieve all associated user interactions (queries and answers) from the `interactions.json` file in S3.
  - **Path Parameter:** `video_id` (string, e.g., `username-tiktokvideoid`)
  - **Response Model:** `StatusResponse` (`video_id`, `processing_status`, `interactions: List[Interaction]`)

## Configuration

Configuration is managed primarily through environment variables. A `.env` file can be used for local development (`python-dotenv` library). `utils.py` loads these into the `CONFIG` dictionary.

**Essential Environment Variables:**

- `AWS_REGION`: AWS region for S3 (e.g., `us-east-1`).
- `S3_BUCKET_NAME`: Name of the S3 bucket used for storage.
- `PINECONE_API_KEY`: API key for Pinecone.
- `PINECONE_INDEX_NAME`: Name of the Pinecone index (e.g., `video-captions-index`).
- `OPENAI_API_KEY`: API key for OpenAI.
- `PERPLEXITY_API_KEY`: API key for Perplexity. **Note:** This is required by the _Perplexity MCP Server_ container, not directly by the backend container, but often managed together.
- `MCP_PERPLEXITY_SSE_URL`: **Crucial.** The full URL (including the `/sse` path) where the Perplexity MCP Server's SSE endpoint is accessible (e.g., `http://mcp-server:8080/sse` in Docker Compose, or the public App Runner URL of the MCP server in production).
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: Required for S3 access if not using IAM instance roles (IAM roles are recommended for production environments like App Runner).

**Optional Environment Variables:**

- `PINECONE_INDEX_HOST`: Pinecone index host (if not provided, `utils.py` will attempt to auto-discover it using the Pinecone API based on `PINECONE_INDEX_NAME`).
- `OPENAI_EMBEDDING_MODEL`: OpenAI model for embeddings (defaults to `text-embedding-ada-002` in `utils.py`).
- `OPENAI_SYNTHESIS_MODEL`: OpenAI model for answer synthesis (defaults to `gpt-4o-mini` in `utils.py`).
- `ANTHROPIC_API_KEY`: API key for Anthropic (required only if using LLM-based tool selection via the MCP server, enabled by default in `pipeline_logic.py`).
- `ANTHROPIC_TOOL_SELECTION_MODEL`: Anthropic model for tool selection (defaults to `claude-3-7-sonnet-20250219` in `utils.py`).

## Local Development & Testing

1.  **Prerequisites:** Docker, Docker Compose.
2.  **Configuration:** Create a `.env` file in the project root directory and populate it with the necessary API keys and configuration values (see above). **Do not commit `.env` to Git.**
3.  **Build Images:** Run `docker compose build` in the project root.
4.  **Run Services:** Run `docker compose up` in the project root. This will start the FastAPI backend (on host port 8000) and the Perplexity MCP Server (on host port 8080).
5.  **Test:** Send requests to `http://localhost:8000` using tools like `curl` or Postman. Monitor logs using `docker compose logs -f backend` and `docker compose logs -f mcp-server`.
6.  **Shutdown:** Press `Ctrl+C` and run `docker compose down`.

## Deployment (AWS App Runner)

1.  **Dockerfile (`backend/Dockerfile`):** Defines the container image build process:
    - Uses a `python:3.10-slim` base image.
    - Sets `WORKDIR /app`.
    - Copies `requirements.txt` and installs dependencies using `pip`.
    - Copies the application code from the local `./app` directory into the container's `/app/app` directory.
    - Exposes port `8000`.
    - Sets the `CMD` to run the application using `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
2.  **ECR:** Build the Docker image and push it to AWS Elastic Container Registry (ECR).
    ```bash
    # Example ECR push commands (replace placeholders)
    aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-account-id>.dkr.ecr.<your-region>.amazonaws.com
    docker build -t video-backend ./backend
    docker tag video-backend:latest <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/video-backend:latest
    docker push <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/video-backend:latest
    ```
3.  **App Runner Service:** Create an App Runner service for the backend:
    - **Source:** Choose "Container registry" and select the ECR image pushed in the previous step.
    - **Port:** Configure the service to listen on port `8000`.
    - **Environment Variables:** Set all the required environment variables (API keys, `S3_BUCKET_NAME`, `PINECONE_INDEX_NAME`, `MCP_PERPLEXITY_SSE_URL` pointing to the **public URL of the deployed Perplexity MCP server App Runner service's /sse endpoint**, etc.) in the App Runner service configuration.
    - **Instance Role:** Configure an IAM role with necessary permissions (e.g., S3 read/write access to the specified bucket, potentially permissions for Pinecone host discovery if needed).
    - **Health Check:** App Runner uses TCP health checks on port 8000 by default. Configure an HTTP health check against the `/` path for more robust checking.
4.  **Deployment:** App Runner pulls the ECR image and deploys the service, providing a public URL for the backend API.

## Dependencies

Key Python libraries are listed in `backend/requirements.txt`. Major ones include:

- `fastapi`, `uvicorn[standard]`: Web framework and ASGI server.
- `starlette`: ASGI toolkit used by FastAPI.
- `pydantic`: Data validation and settings management.
- `boto3`: AWS SDK for Python (for S3).
- `openai`: OpenAI API client library.
- `pinecone-client[grpc]`: Pinecone vector database client library (using gRPC).
- `fastmcp`: Client library for the Model Context Protocol (FastMCP variant).
- `httpx`, `httpx-sse`: Asynchronous HTTP client libraries (required by `fastmcp` for SSE transport).
- `anthropic`: Anthropic API client library (optional, for LLM tool selection).
- `python-dotenv`: For loading `.env` files during local development.
- Video Processing (Included but logic is currently placeholder):
  - `yt_dlp`: For downloading videos.
  - `moviepy`: For video editing tasks (like chunking).
  - `TikTokApi`: Potentially used for TikTok specific interactions (check usage).
  - `scenedetect`: For detecting scene changes (used in chunking).
  - `opencv-python`: Computer vision library, often a dependency for video processing.
- `google-genai`: Google Generative AI client for generating high quality captions with `gemini-2.5-pro-preview-03-25`
- `mcp`: Original MCP library
