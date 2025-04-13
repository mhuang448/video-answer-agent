/**
 * Common Types for the Video Answer Agent Application
 */

// Basic Video Information
export interface VideoInfo {
  video_id: string;
  video_url: string;
  like_count: number;
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
