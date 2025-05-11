import { NextResponse } from "next/server";

export interface QueryRequest {
  video_id: string;
  user_query: string;
  user_name: string;
}

export interface ProcessingStartedResponse {
  status: string;
  video_id: string;
  interaction_id: string;
}

const API_BASE_URL = process.env.BACKEND_API_URL;

/**
 * POST handler for querying a processed video
 * Proxies the request to our FastAPI backend
 */
export async function POST(request: Request) {
  try {
    const body: QueryRequest = await request.json();

    // Basic validation
    if (!body.video_id || !body.user_query || !body.user_name) {
      return NextResponse.json(
        {
          error: "Missing required fields: video_id, user_query, or user_name",
        },
        { status: 400 }
      );
    }

    const response = await fetch(`${API_BASE_URL}/api/query/async`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `Failed to submit query: ${response.statusText}` },
        { status: response.status }
      );
    }

    const data: ProcessingStartedResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error submitting query:", error);
    return NextResponse.json(
      { error: "Failed to process query request" },
      { status: 500 }
    );
  }
}
