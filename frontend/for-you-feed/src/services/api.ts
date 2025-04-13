// API endpoints for interacting with our FastAPI backend
const API_BASE_URL = "http://localhost:8000";

// Types based on our backend models
export interface VideoInfo {
  video_id: string;
  video_url: string;
  like_count: number;
  uploader_name?: string;
}

export interface LikeResponse {
  like_count: number;
}

// Function to fetch videos for the For You feed
export const fetchForYouVideos = async (): Promise<VideoInfo[]> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/videos/foryou`);

    if (!response.ok) {
      throw new Error(`Failed to fetch videos: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error("Error fetching videos:", error);
    return [];
  }
};

// Function to like a video
export const likeVideo = async (videoId: string): Promise<number> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/videos/${videoId}/like`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to like video: ${response.status}`);
    }

    const data: LikeResponse = await response.json();
    return data.like_count;
  } catch (error) {
    console.error("Error liking video:", error);
    throw error;
  }
};
