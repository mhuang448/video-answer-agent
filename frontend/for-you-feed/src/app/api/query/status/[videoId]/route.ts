import { NextRequest, NextResponse } from "next/server";
import { StatusResponse } from "@/app/types";

const API_BASE_URL = process.env.BACKEND_API_URL;

/**
 * GET handler for checking video processing and query status
 * Proxies the request to our FastAPI backend
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ videoId: string }> }
) {
  // Await params as suggested by the solution
  const { videoId } = await params;

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
