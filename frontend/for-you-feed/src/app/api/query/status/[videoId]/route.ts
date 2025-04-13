import { NextRequest, NextResponse } from "next/server";

export interface Interaction {
  interaction_id: string;
  user_name?: string;
  user_query: string;
  query_timestamp: string;
  status: string;
  ai_answer?: string;
  answer_timestamp?: string;
}

export interface StatusResponse {
  processing_status?: string;
  video_url?: string;
  like_count?: number;
  uploader_name?: string;
  interactions: Interaction[];
}

const API_BASE_URL = "http://localhost:8000";

/**
 * GET handler for checking video processing and query status
 * Proxies the request to our FastAPI backend
 */
export async function GET(
  request: NextRequest,
  { params }: { params: { videoId: string } }
) {
  // Using object destructuring to properly access params
  const { videoId } = params;

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/query/status/${videoId}`,
      {
        headers: {
          "Content-Type": "application/json",
        },
        // Choosing not to cache this response as it frequently changes
        cache: "no-store",
      }
    );

    if (!response.ok) {
      return NextResponse.json(
        { error: `Failed to fetch query status: ${response.statusText}` },
        { status: response.status }
      );
    }

    const data: StatusResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error fetching query status:", error);
    return NextResponse.json(
      { error: "Failed to fetch query status" },
      { status: 500 }
    );
  }
}
