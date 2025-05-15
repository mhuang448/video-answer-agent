import { VideoInfo } from "@/app/types";

/**
 * Service component for fetching video data
 * Abstracts the API calling logic
 */
const VideoDataProvider = {
  /**
   * Fetches initial videos for the For You feed.
   * When called server-side (e.g., from a Server Component like page.tsx),
   * this function directly calls the FastAPI backend.
   * No caching to ensure fresh random videos on every request.
   */
  async getForYouVideos(): Promise<VideoInfo[]> {
    const backendApiUrl = process.env.BACKEND_API_URL;

    if (!backendApiUrl) {
      console.error(
        "ERROR: BACKEND_API_URL is not set in the environment. " +
          "VideoDataProvider cannot fetch videos directly from the backend."
      );
      // In a real-world scenario, you might throw an error or return a more specific error state.
      return [];
    }

    try {
      // Directly fetch from the FastAPI backend endpoint
      const response = await fetch(`${backendApiUrl}/api/videos/foryou`, {
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store", // Ensure we're not caching the FastAPI response
      });

      if (!response.ok) {
        console.error(`Failed to fetch videos: ${response.status}`);
        return [];
      }

      console.log("Fetched fresh videos from API");

      return await response.json();
    } catch (error) {
      console.error("Error fetching videos:", error);
      return [];
    }
  },
};

export default VideoDataProvider;
