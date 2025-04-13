import { VideoInfo } from "@/app/types";

/**
 * Service component for fetching video data
 * Abstracts the API calling logic
 */
const VideoDataProvider = {
  /**
   * Fetches initial videos for the For You feed
   * Uses the Next.js API route to get data from FastAPI backend
   * No caching to ensure fresh random videos on every request
   */
  async getForYouVideos(): Promise<VideoInfo[]> {
    try {
      // Use the absolute URL of our Next.js API route
      // In production, you'd use your deployed URL
      const baseUrl =
        process.env.NODE_ENV === "production"
          ? "https://your-production-url.com" // Replace with your actual production URL
          : "http://localhost:3000";

      // Using cache: 'no-store' to ensure we get fresh videos on every request
      const response = await fetch(`${baseUrl}/api/videos/foryou`, {
        cache: "no-store", // Disable caching completely - get fresh data every time
      });

      if (!response.ok) {
        console.error(`Failed to fetch videos: ${response.status}`);
        return [];
      }

      // Log that we're fetching fresh data
      console.log("Fetched fresh videos from API");

      return await response.json();
    } catch (error) {
      console.error("Error fetching videos:", error);
      return [];
    }
  },
};

export default VideoDataProvider;
