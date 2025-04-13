/**
 * Common Types for the Video Answer Agent Application
 */

// Basic Video Information - Feed/Display Related
export interface VideoInfo {
  video_id: string;
  video_url: string;
  like_count: number;
  comment_count?: number; // Optional, could be derived from interactions length
  uploader_name?: string;
  interactions?: Interaction[]; // Interactions might be fetched separately
}

// --- API Request/Response Types (Matching Backend Models) ---

// Like Request Response
export interface LikeResponse {
  like_count: number;
}

// Query Request Body (POST /api/query/async)
export interface QueryRequest {
  video_id: string;
  user_query: string;
  user_name: string; // Added user_name
}

// Process Request Body (POST /api/process_and_query/async)
export interface ProcessRequest {
  video_url: string;
  user_query: string;
  user_name: string; // Added user_name
  uploader_name?: string;
}

// Response for Async Processing Start (Common for Query and Process)
export interface ProcessingStartedResponse {
  status: string;
  video_id: string;
  interaction_id: string;
}

// A single Q&A interaction - This is the core data structure for comments/answers
export interface Interaction {
  interaction_id: string;
  user_name?: string; // The user who asked the question
  user_query: string;
  query_timestamp: string; // ISO 8601 format string
  status: "processing" | "completed" | "failed"; // Define possible statuses
  ai_answer?: string; // Answer is optional until status is 'completed'
  answer_timestamp?: string; // ISO 8601 format string
}

// Status Response (GET /api/query/status/{video_id})
export interface StatusResponse {
  processing_status?: "PROCESSING" | "FINISHED" | "FAILED" | string; // Overall video status
  video_url?: string; // Public S3 URL
  like_count?: number;
  uploader_name?: string;
  interactions: Interaction[]; // The list of Q&A interactions for the video
}

// --- Removed Comment Type ---
// The Interaction type now covers the necessary information for displaying comments/queries/answers.
// export interface Comment {
//   id: string; // Unique identifier for the comment
//   videoId: string; // ID of the video this comment belongs to
//   author: string; // Name of the commenter (placeholder for now)
//   text: string; // The content of the comment
//   timestamp: Date; // When the comment was submitted
// }
