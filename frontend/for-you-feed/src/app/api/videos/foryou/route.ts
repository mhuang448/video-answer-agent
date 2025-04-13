import { NextResponse } from "next/server";
import { VideoInfo } from "@/app/types";

const API_BASE_URL = "http://localhost:8000";

/**
 * GET handler for fetching videos for the For You feed
 * Proxies the request to our FastAPI backend
 * No caching to ensure fresh random videos every time
 */
export async function GET() {
  console.log("API Route: Fetching fresh videos from FastAPI backend");

  try {
    const response = await fetch(`${API_BASE_URL}/api/videos/foryou`, {
      headers: {
        "Content-Type": "application/json",
      },
      cache: "no-store", // Ensure we're not caching the FastAPI response
    });

    if (!response.ok) {
      console.error(
        `Failed to fetch videos from backend: ${response.status} ${response.statusText}`
      );
      return NextResponse.json(
        { error: `Failed to fetch videos: ${response.statusText}` },
        { status: response.status }
      );
    }

    const videos: VideoInfo[] = await response.json();
    console.log(`Received ${videos.length} videos from backend`);

    return NextResponse.json(videos);
  } catch (error) {
    console.error("Error fetching videos:", error);
    return NextResponse.json(
      { error: "Failed to fetch videos from backend" },
      { status: 500 }
    );
  }
}
