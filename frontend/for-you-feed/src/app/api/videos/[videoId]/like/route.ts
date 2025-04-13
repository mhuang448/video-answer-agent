import { NextRequest, NextResponse } from "next/server";

export interface LikeResponse {
  like_count: number;
}

const API_BASE_URL = "http://localhost:8000";

/**
 * POST handler for liking a video
 * Proxies the request to our FastAPI backend
 */
export async function POST(
  request: NextRequest,
  { params }: { params: { videoId: string } }
) {
  // Using object destructuring to properly access params
  const { videoId } = params;

  try {
    const response = await fetch(`${API_BASE_URL}/api/videos/${videoId}/like`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `Failed to like video: ${response.statusText}` },
        { status: response.status }
      );
    }

    const data: LikeResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error liking video:", error);
    return NextResponse.json(
      { error: "Failed to process like request" },
      { status: 500 }
    );
  }
}
