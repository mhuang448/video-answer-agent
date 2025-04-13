import { NextResponse } from "next/server";

export interface ProcessRequest {
  video_url: string;
  user_query: string;
  user_name: string;
  uploader_name?: string;
}

export interface ProcessingStartedResponse {
  status: string;
  video_id: string;
  interaction_id: string;
}

const API_BASE_URL = "http://localhost:8000";

/**
 * POST handler for processing a new video and querying it
 * Proxies the request to our FastAPI backend
 */
export async function POST(request: Request) {
  try {
    const body: ProcessRequest = await request.json();

    // Basic validation
    if (!body.video_url || !body.user_query || !body.user_name) {
      return NextResponse.json(
        {
          error: "Missing required fields: video_url, user_query, or user_name",
        },
        { status: 400 }
      );
    }

    const response = await fetch(
      `${API_BASE_URL}/api/process_and_query/async`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      }
    );

    if (!response.ok) {
      return NextResponse.json(
        { error: `Failed to process video: ${response.statusText}` },
        { status: response.status }
      );
    }

    const data: ProcessingStartedResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error processing video:", error);
    return NextResponse.json(
      { error: "Failed to process video request" },
      { status: 500 }
    );
  }
}
