/**
 * Common Types for the Video Answer Agent Application
 */

// Basic Video Information
export interface VideoInfo {
  video_id: string;
  video_url: string;
  like_count: number;
  comment_count?: number;
  uploader_name?: string;
}

// Like Request Response
export interface LikeResponse {
  like_count: number;
}

// Query Request
export interface QueryRequest {
  video_id: string;
  user_query: string;
  user_name: string;
}

// Process Request for new videos
export interface ProcessRequest {
  video_url: string;
  user_query: string;
  user_name: string;
  uploader_name?: string;
}

// Response for Async Processing Start
export interface ProcessingStartedResponse {
  status: string;
  video_id: string;
  interaction_id: string;
}

// A single Q&A interaction
export interface Interaction {
  interaction_id: string;
  user_name?: string;
  user_query: string;
  query_timestamp: string;
  status: string;
  ai_answer?: string;
  answer_timestamp?: string;
}

// Status Response with video processing status and interactions
export interface StatusResponse {
  processing_status?: string;
  video_url?: string;
  like_count?: number;
  uploader_name?: string;
  interactions: Interaction[];
}

/**
 * Represents a single comment on a video.
 */
export interface Comment {
  id: string; // Unique identifier for the comment
  videoId: string; // ID of the video this comment belongs to
  author: string; // Name of the commenter (placeholder for now)
  text: string; // The content of the comment
  timestamp: Date; // When the comment was submitted
}
