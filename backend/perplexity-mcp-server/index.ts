#!/usr/bin/env node

import { FastMCP, UserError, FastMCPSession, Context } from "fastmcp";
import { z } from "zod";
import dotenv from "dotenv";

// --- EDIT: Remove Global Error Handlers (rely on session handler for now) ---
// process.on("uncaughtException", ...);
// process.on("unhandledRejection", ...);
// --- END EDIT ---

dotenv.config();

/**
 * Definition of the Perplexity Ask Tool.
 * This tool accepts an array of messages and returns a chat completion response
 * from the Perplexity API, with citations appended to the message if provided.
 */
const PERPLEXITY_ASK_TOOL_DESC = `
  Ask Tool: Fast Latency - Quick and Accurate Fact-Based Responses

This tool provides rapid responses grounded firmly in verifiable truth, leveraging fast internet queries optimized for low latency and cost efficiency. It is ideal for straightforward Q&A tasks that require quick fact retrieval, simple calculations, brief historical facts, or concise explanations of widely understood topics. Use this tool for immediate, factual information needs where speed is prioritized over in-depth analysis or comprehensive reasoning.

**When to Use:**
- Simple math calculations, dates, and numerical data retrieval
- Basic historical fact-checking (e.g., dates, events, places)
- Straightforward definitions or explanations of well-established concepts

**When to Avoid:**
- Complex or nuanced topics requiring reasoning or multi-step analysis
- Questions requiring detailed citations or extensive research support
  `;

/**
 * Definition of the Perplexity Reason Tool.
 * This tool performs reasoning queries using the Perplexity API.
 */
const PERPLEXITY_REASON_TOOL_DESC = `
Reasoning Tool: Medium Latency - Advanced Reasoning and Detailed Explanations

This high-performance tool employs sophisticated multi-step chain-of-thought (CoT) reasoning combined with advanced internet information retrieval to produce thorough, reasoned, and contextually rich answers. It is best suited for moderately complex tasks, topics requiring logical deductions, multi-step calculations, or detailed reasoning beyond simple facts. It balances speed with analytical depth, making it ideal for situations demanding thoughtful exploration of a question without the need for exhaustive citations.

**When to Use:**
- Moderately complex inquiries involving logical reasoning or explanations
- Multi-step problems such as algebraic calculations, scientific reasoning, or cause-and-effect analysis
- Tasks requiring synthesized understanding from multiple pieces of information

**When to Avoid:**
- Extremely simple, factual queries where \`perplexity_ask\` tool would suffice
- Very in-depth or scholarly research needing extensive citations and exhaustive detail
  `;

/**
 * Definition of the Perplexity Research Tool.
 * This tool performs deep research queries using the Perplexity API.
 */
// const PERPLEXITY_RESEARCH_TOOL_DESC = ...; // Add if needed

// Retrieve the Perplexity API key from environment variables
const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
if (!PERPLEXITY_API_KEY) {
  console.error("ERROR: PERPLEXITY_API_KEY environment variable is required");
  process.exit(1);
} else {
  console.log("INFO: PERPLEXITY_API_KEY loaded successfully.");
}

/**
 * Performs a chat completion by sending a request to the Perplexity API.
 * Appends citations to the returned message content if they exist.
 *
 * @param {Array<{ role: string; content: string }>} messages - An array of message objects.
 * @param {string} model - The model to use for the completion.
 * @returns {Promise<string>} The chat completion result with appended citations.
 * @throws Will throw an error if the API request fails.
 */
async function performChatCompletion(
  messages: Array<{ role: string; content: string }>,
  model: string = "sonar-pro",
  logPrefix: string = "[API]"
): Promise<string> {
  const url = new URL("https://api.perplexity.ai/chat/completions");
  const body = {
    model: model,
    messages: messages,
  };

  console.log(`${logPrefix} Calling Perplexity API (model: ${model})...`);
  let response;
  try {
    response = await fetch(url.toString(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${PERPLEXITY_API_KEY}`,
      },
      body: JSON.stringify(body),
    });
  } catch (error) {
    console.error(`${logPrefix} Network error calling Perplexity API:`, error);
    // Re-throw a more specific error for the tool handler
    throw new Error(
      `Network error while calling Perplexity API: ${
        error instanceof Error ? error.message : String(error)
      }`
    );
  }

  if (!response.ok) {
    let errorText = "Unknown API error";
    try {
      errorText = await response.text();
    } catch (parseError) {
      console.error(
        `${logPrefix} Failed to parse error response body from Perplexity API`
      );
    }
    console.error(
      `${logPrefix} Perplexity API error: ${response.status} ${response.statusText}`,
      errorText
    );
    // Re-throw a more specific error
    throw new Error(
      `Perplexity API error: ${response.status} ${response.statusText}\n${errorText}`
    );
  }

  let data;
  try {
    data = await response.json();
  } catch (jsonError) {
    console.error(
      `${logPrefix} Failed to parse JSON response from Perplexity API:`,
      jsonError
    );
    // Re-throw a more specific error
    throw new Error(
      `Failed to parse JSON response from Perplexity API: ${
        jsonError instanceof Error ? jsonError.message : String(jsonError)
      }`
    );
  }

  console.log(`${logPrefix} Perplexity API call successful (model: ${model}).`);
  let messageContent =
    data.choices[0]?.message?.content ?? "[No content received]";

  if (
    data.citations &&
    Array.isArray(data.citations) &&
    data.citations.length > 0
  ) {
    messageContent += "\n\nCitations:\n";
    data.citations.forEach((citation: any, index: number) => {
      messageContent += `[${index + 1}] ${JSON.stringify(citation)}\n`;
    });
  }

  return messageContent;
}

console.log("INFO: Initializing FastMCP server...");
const server = new FastMCP<undefined>({
  name: "perplexity-fastmcp-server",
  version: "0.1.0",
});
console.log("INFO: FastMCP server instance created.");

const port = parseInt(process.env.PORT || "8080", 10);
const sseEndpoint = "/sse"; // Default endpoint path
console.log(`INFO: Configured Port: ${port}, SSE Endpoint: ${sseEndpoint}`);

// Define shared message schema using Zod
const messageSchema = z.object({
  role: z
    .string()
    .describe("Role of the message (e.g., system, user, assistant)"),
  content: z.string().describe("The content of the message"),
});
const messagesSchema = z
  .array(messageSchema)
  .describe("Array of conversation messages");
const toolInputSchema = z
  .object({
    messages: messagesSchema,
  })
  .describe(
    "Input schema for Perplexity tools requiring conversation history."
  );

// Add Perplexity Ask Tool
console.log("INFO: Adding tool 'perplexity_ask'...");
server.addTool({
  name: "perplexity_ask",
  description: PERPLEXITY_ASK_TOOL_DESC,
  parameters: toolInputSchema,
  execute: async (
    args: z.infer<typeof toolInputSchema>,
    context: Context<undefined>
  ) => {
    // --- EDIT: Use context.log for logging ---
    const toolName = "perplexity_ask";
    context.log.info(`Executing tool: ${toolName}`); // Rely on framework to add context
    try {
      if (!args.messages || args.messages.length === 0) {
        context.log.warn("Input 'messages' array is empty.");
        throw new UserError("Input 'messages' array cannot be empty.");
      }

      // Pass a simple prefix for the external API call function
      const resultText = await performChatCompletion(
        args.messages,
        "sonar-pro",
        `[API:${toolName}]`
      );

      context.log.info(`Execution successful: ${toolName}`);
      return resultText;
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      const errorStack = error instanceof Error ? error.stack : "";
      // Log the error using the context logger
      context.log.error(`Execution failed: ${toolName}: ${errorMessage}`, {
        stack: errorStack,
      });
      // Throw UserError to send clean error to client
      throw new UserError(`Failed to execute ${toolName}: ${errorMessage}`);
    }
    // --- END EDIT ---
  },
});
console.log("INFO: Tool 'perplexity_ask' added.");

// Add Perplexity Reason Tool
console.log("INFO: Adding tool 'perplexity_reason'...");
server.addTool({
  name: "perplexity_reason",
  description: PERPLEXITY_REASON_TOOL_DESC,
  parameters: toolInputSchema,
  execute: async (
    args: z.infer<typeof toolInputSchema>,
    context: Context<undefined>
  ) => {
    // --- EDIT: Use context.log for logging ---
    const toolName = "perplexity_reason";
    context.log.info(`Executing tool: ${toolName}`);
    try {
      if (!args.messages || args.messages.length === 0) {
        context.log.warn("Input 'messages' array is empty.");
        throw new UserError("Input 'messages' array cannot be empty.");
      }

      const resultText = await performChatCompletion(
        args.messages,
        "sonar-reasoning-pro",
        `[API:${toolName}]`
      );

      context.log.info(`Execution successful: ${toolName}`);
      return resultText;
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      const errorStack = error instanceof Error ? error.stack : "";
      context.log.error(`Execution failed: ${toolName}: ${errorMessage}`, {
        stack: errorStack,
      });
      throw new UserError(`Failed to execute ${toolName}: ${errorMessage}`);
    }
    // --- END EDIT ---
  },
});
console.log("INFO: Tool 'perplexity_reason' added.");

// Health check resource
console.log("INFO: Adding resource 'health://status'...");
server.addResource({
  uri: "health://status",
  name: "Server Health",
  description: "Returns OK if the server is running.",
  mimeType: "text/plain",
  async load() {
    // Static resource load signature
    console.log("[HEALTH] Health check requested."); // Use console log as context isn't passed
    return { text: "OK" };
  },
});
console.log("INFO: Resource 'health://status' added.");

// Start the server with SSE transport
console.log(
  `INFO: Attempting to start FastMCP server on port ${port} (endpoint: ${sseEndpoint})...`
);
try {
  server.start({
    transportType: "sse",
    sse: {
      endpoint: sseEndpoint,
      port: port,
    },
  });
  console.log(
    `INFO: FastMCP Perplexity Server listening on port ${port} at endpoint ${sseEndpoint}`
  );
} catch (error) {
  console.error("FATAL: Failed to start FastMCP server:", error);
  process.exit(1);
}

// --- EDIT: Refined Error/Disconnect Handling ---
// Use a WeakSet to track sessions we're already trying to close due to error
const closingSessions = new WeakSet<FastMCPSession<undefined>>();

server.on("connect", (event: { session: FastMCPSession<undefined> }) => {
  console.log(`EVENT: Client connected.`);
  const session = event.session;

  session.on("error", (sessionEvent: { error: Error }) => {
    console.error(
      `EVENT: Error on session. Reason: ${
        sessionEvent.error?.stack || sessionEvent.error
      }`
    );

    // Only attempt to close if we haven't already started closing this session
    if (session && !closingSessions.has(session)) {
      console.log(`Attempting to close errored session...`);
      closingSessions.add(session); // Mark session as closing
      session
        .close()
        .then(() => {
          console.log(`Errored session closed successfully.`);
          // Optional: remove from WeakSet if needed, but GC should handle it
        })
        .catch((err) => {
          console.error(`Error closing errored session:`, err);
          // Optional: remove from WeakSet if close fails badly
        }); // No finally needed here as subsequent errors for this session will be ignored
    } else if (closingSessions.has(session)) {
      console.log(`Ignoring subsequent error on already closing session.`);
    } else {
      // Session object was somehow unavailable
      console.warn(
        "Error event received but session object was unavailable for closing."
      );
    }
  });
});

server.on("disconnect", (event: { session: FastMCPSession<undefined> }) => {
  console.log(`EVENT: Client disconnected.`);
  const session = event.session;

  // Only attempt close here if it wasn't already initiated by the error handler
  if (session && !closingSessions.has(session)) {
    console.log(`Attempting to close normally disconnected session...`);
    // No need to add to closingSessions here, as disconnect should only fire once?
    session
      .close()
      .then(() => {
        console.log(`Disconnected session closed successfully.`);
      })
      .catch((err) => {
        console.error(`Error closing normally disconnected session:`, err);
      });
  } else if (closingSessions.has(session)) {
    console.log(`Session already closed due to prior error.`);
  } else {
    console.warn("Disconnect event received but session object was undefined.");
  }
});
// --- END EDIT ---
