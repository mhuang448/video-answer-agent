export type VideoInfo = {
  video_id: string;
  video_url: string;
  uploader_name?: string;
  description?: string;
  // Add other relevant fields like likes, comments, shares later
  like_count?: number;
  comment_count?: number;
  share_count?: number;
};

/**
 * Represents a single comment on a video.
 */
export type Comment = {
  id: string; // Unique identifier for the comment
  videoId: string; // ID of the video this comment belongs to
  author: string; // Name of the commenter (placeholder for now)
  text: string; // The content of the comment
  timestamp: Date; // When the comment was submitted
};
