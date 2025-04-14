# SSE-Enabled Perplexity MCP Server

(FastMCP Node.js MCP Server)

An MCP server implementation using **FastMCP** that integrates the Perplexity Sonar API to provide MCP clients (like our Python backend) with real-time, web-wide research and reasoning capabilities via **Server-Sent Events (SSE)**.

This server is built with Node.js and TypeScript, using the `fastmcp` library for the core MCP functionality.

## Implementation Notes & Acknowledgements

This Node.js server is adapted from Perplexity's official `perplexity-ask` MCP server example, available in the `modelcontextprotocol` repository ([view example](https://github.com/ppl-ai/modelcontextprotocol/tree/main/example-servers/perplexity-ask)).

The original example utilized Perplexity's `sdk/server` library and communicated via **Standard Input/Output (Stdio)** using `StdioServerTransport`. This approach is suitable for direct process control, such as a desktop application launching the server locally.

However, our architecture requires the Python backend service (running potentially in a separate container or AWS App Runner instance) to communicate with this MCP server over the network. Stdio is not suitable for this network-based, decoupled communication. Therefore, we modified the implementation significantly:

1.  **Switched to `fastmcp`:** We adopted the `fastmcp` TypeScript library for MCP server/client implementation.
2.  **Adopted SSE Transport:** We configured `fastmcp` to use its built-in **Server-Sent Events (SSE)** transport (`server.start({ transportType: 'sse', ... })`). This allows the server to listen on a network port (default `8080`) and communicate with clients (like our Python backend using its `fastmcp` client and `httpx-sse`) over standard HTTP.

This change enables the necessary network interaction between our distributed services.

## Overview

- **Protocol:** FastMCP over HTTP/SSE
- **Implementation:** Node.js, TypeScript, `fastmcp` library, `dotenv`, `zod`
- **Core Logic:** `index.ts`
- **Transport:** Exposes an SSE endpoint (default: `/sse`) on a configurable port (default: `8080`).

## Tools Exposed via FastMCP

The server exposes the following tools, which the Python backend can call using its `fastmcp` client:

- **`perplexity_ask`**

  - **Description:** Provides rapid, fact-based responses using the Perplexity Sonar API (`sonar-pro` model) optimized for low latency. Ideal for simple Q&A, fact retrieval, calculations, etc.
  - **Inputs (Zod Schema: `toolInputSchema`):**
    - `messages` (array): An array of conversation messages.
      - Each message must include:
        - `role` (string): Role (`system`, `user`, `assistant`).
        - `content` (string): Message content.
  - **Output:** A string containing the chat completion result from Perplexity, potentially with citations appended.
  - **Underlying API Call:** `performChatCompletion(messages, "sonar-pro")` to `https://api.perplexity.ai/chat/completions`.

- **`perplexity_reason`**
  - **Description:** Performs more complex reasoning using the Perplexity Sonar API (`sonar-reasoning-pro` model). Suitable for multi-step reasoning, logical deductions, and synthesized understanding.
  - **Inputs (Zod Schema: `toolInputSchema`):** Same as `perplexity_ask`.
  - **Output:** A string containing the chat completion result from Perplexity.
  - **Underlying API Call:** `performChatCompletion(messages, "sonar-reasoning-pro")`.

_(Note: A `perplexity_research` tool to query Perplexity's `sonar-deep-research` model was also included in original perplexity-ask MCP Server, but omitted for latency optimization)._

## Resources Exposed via FastMCP

- **`health://status`**
  - **Description:** A simple health check resource.
  - **Output:** Returns the plain text string "OK".

## Configuration

Configuration is managed via environment variables, loaded using `dotenv`.

- **`PERPLEXITY_API_KEY` (Required):** Your API key obtained from Perplexity AI ([docs](https://docs.perplexity.ai/guides/getting-started)). This is essential for the server to call the Perplexity API.
- **`PORT` (Optional):** The port number the server should listen on. Defaults to `8080`.

## Running the Server

### 1. Prerequisites

- Node.js (version 22 or compatible, as per `Dockerfile`)
- npm
- Docker (for containerized deployment)

### 2. Installation

Clone the repository (if you haven't already) and navigate to the `backend/perplexity-mcp-server` directory.

Install dependencies:

```bash
npm install
```

This will also likely compile the TypeScript code (check `package.json` scripts).

### 3. Environment Setup

Create a `.env` file in the `backend/perplexity-mcp-server` directory:

```dotenv
# .env file for Perplexity MCP Server
PERPLEXITY_API_KEY=YOUR_PERPLEXITY_API_KEY_HERE
PORT=8080 # Optional, defaults to 8080
```

Replace `YOUR_PERPLEXITY_API_KEY_HERE` with your actual key.

### 4. Running Locally

You can typically run the compiled JavaScript file directly:

```bash
node dist/index.js
```

The server will start and log messages indicating it's listening on the configured port and SSE endpoint (e.g., `INFO: FastMCP Perplexity Server listening on port 8080 at endpoint /sse`).

### 5. Running with Docker

The provided `Dockerfile` facilitates containerization.

**a) Build the Docker Image:**

Navigate to the `backend/perplexity-mcp-server` directory.

```bash
# Build the image, tagging it for clarity
docker build -t perplexity-mcp-server:latest .
```

**b) Run the Docker Container:**

```bash
docker run --rm -p 8080:8080 \
  --env PERPLEXITY_API_KEY=YOUR_PERPLEXITY_API_KEY_HERE \
  --name mcp-server-container \
  perplexity-mcp-server:latest
```

- `--rm`: Automatically removes the container when it exits.
- `-p 8080:8080`: Maps port 8080 on your host machine to port 8080 inside the container (where the server listens).
- `--env PERPLEXITY_API_KEY=...`: Passes the required API key as an environment variable to the container.
- `--name mcp-server-container`: Assigns a name to the running container for easier management.
- `perplexity-mcp-server:latest`: Specifies the image to run.

The container will start, and the server inside it will begin listening.

## Deployment (AWS App Runner)

Similar to the Python backend, this Node.js MCP server can be deployed using AWS App Runner.

1.  **Dockerfile (`backend/perplexity-mcp-server/Dockerfile`):**
    - Uses a multi-stage build (`node:22.12-alpine` for building, `node:22-alpine` for the final release image).
    - Copies `package.json`, `package-lock.json`.
    - Installs production dependencies using `npm ci --omit=dev`.
    - Copies the compiled code (`dist` directory) from the builder stage.
    - Sets `NODE_ENV=production`.
    - **Exposes port `8080`.**
    - Sets the `ENTRYPOINT` to `["node", "dist/index.js"]`.
2.  **ECR:** Build the Docker image and push it to AWS Elastic Container Registry (ECR).
    ```bash
    # Example ECR push commands (replace placeholders)
    # Login to ECR
    aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-account-id>.dkr.ecr.<your-region>.amazonaws.com
    # Build the image (ensure you are in the backend/perplexity-mcp-server directory)
    docker build -t perplexity-mcp-server .
    # Tag the image
    docker tag perplexity-mcp-server:latest <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/perplexity-mcp-server:latest
    # Push the image
    docker push <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/perplexity-mcp-server:latest
    ```
3.  **App Runner Service:** Create a _separate_ App Runner service for the MCP server:
    - **Source:** Choose "Container registry" and select the ECR image pushed in the previous step (e.g., `<your-account-id>.dkr.ecr.<your-region>.amazonaws.com/perplexity-mcp-server:latest`).
    - **Port:** Configure the service to listen on port `8080`.
    - **Environment Variables:**
      - Set `PERPLEXITY_API_KEY` to your actual Perplexity API key.
      - You _can_ set `PORT` to `8080` explicitly, but App Runner typically maps its internal port correctly based on the EXPOSE instruction.
    - **Instance Role:** Usually, no specific IAM role is needed unless the server requires access to other AWS services (which this one currently doesn't).
    - **Health Check:** App Runner's default TCP health check on port `8080` should suffice. You could potentially configure an HTTP health check against the `/sse` endpoint, although SSE endpoints might behave differently than standard HTTP GET for health checks.
4.  **Deployment:** App Runner pulls the ECR image and deploys the MCP server, providing a public URL (e.g., `https://<app-runner-service-id>.<region>.awsapprunner.com`).
5.  **Backend Configuration:** **Crucially**, take the public URL provided by App Runner for _this MCP server service_ and set it as the value for the `MCP_PERPLEXITY_SSE_URL` environment variable in the _Python backend's_ App Runner service configuration (e.g., `MCP_PERPLEXITY_SSE_URL=https://<mcp-app-runner-service-id>.<region>.awsapprunner.com/sse`).

## Error Handling

- The server uses `try...catch` blocks within the tool `execute` functions.
- Errors during the Perplexity API call (`performChatCompletion`) are caught and re-thrown as standard `Error` objects.
- Tool execution errors are caught, logged using the `context.log.error` provided by FastMCP, and then thrown as `UserError` to send a cleaner error message back to the MCP client.
- `index.ts` includes `server.on('connect', ...)` and `server.on('disconnect', ...)` handlers with basic error logging for session-level issues and attempts to close errored sessions gracefully.

## Dependencies (Key)

- `fastmcp`: Core library for implementing the MCP server.
- `zod`: Used for defining and validating the input schemas for the tools.
- `dotenv`: Loads environment variables from a `.env` file for local development.
- `@types/*`: TypeScript type definitions.

## License

This MCP server is licensed under the MIT License. See the main project repository for details.
