"use client";

import React, { useState, useRef, useEffect } from "react";
import { VideoInfo } from "@/app/types";
import VideoPlayer from "./VideoPlayer";
import VideoActionsBar from "./VideoActionsBar";
import CommentSidebar from "./CommentSidebar";

interface VideoFeedProps {
  initialVideos: VideoInfo[];
}

/**
 * Client component for handling the TikTok-style vertical video feed
 * Uses CSS Scroll Snap for smooth snapping between videos
 * Ensures only one video plays at a time using Intersection Observer
 */
const VideoFeed = ({ initialVideos }: VideoFeedProps) => {
  // In a real app, you might fetch more videos on scroll, but
  // for this example, we'll just use the initial set
  const [videos] = useState<VideoInfo[]>(initialVideos);
  // Track which video is currently active/visible
  const [activeVideoId, setActiveVideoId] = useState<string | null>(
    initialVideos.length > 0 ? initialVideos[0].video_id : null
  );
  // State for comment sidebar visibility and context
  const [isCommentSidebarOpen, setIsCommentSidebarOpen] = useState(false);
  const [commentVideoId, setCommentVideoId] = useState<string | null>(null);

  // Container ref for the scrollable area
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // Refs for tracking intersection observer entries
  const observers = useRef<Map<string, IntersectionObserver>>(new Map());

  // Set up intersection observers for each video
  useEffect(() => {
    if (!scrollContainerRef.current) return;

    // Cleanup previous observers
    observers.current.forEach((observer) => observer.disconnect());
    observers.current.clear();

    // Create new observers for each video
    videos.forEach((video) => {
      const videoId = video.video_id;
      const element = document.getElementById(`video-container-${videoId}`);

      if (element) {
        const observer = new IntersectionObserver(
          (entries) => {
            const entry = entries[0];

            if (entry.isIntersecting && entry.intersectionRatio >= 0.7) {
              // This video is now mostly visible
              setActiveVideoId(videoId);
              // Close comments if user scrolls to a new video
              // handleCloseComments(); // Optional: Decide if you want this behavior
            }
          },
          {
            root: scrollContainerRef.current,
            threshold: 0.7, // 70% of the video must be visible
          }
        );

        observer.observe(element);
        observers.current.set(videoId, observer);
      }
    });

    // Auto-play the first video if not already set
    if (videos.length > 0 && !activeVideoId) {
      setActiveVideoId(videos[0].video_id);
    }

    // Cleanup when component unmounts
    return () => {
      observers.current.forEach((observer) => observer.disconnect());
      observers.current.clear();
    };
  }, [videos, activeVideoId, isCommentSidebarOpen]); // Added isCommentSidebarOpen to deps if needed for the optional logic

  // --- Comment Sidebar Handlers ---
  const handleOpenComments = (videoId: string) => {
    setCommentVideoId(videoId);
    setIsCommentSidebarOpen(true);
  };

  const handleCloseComments = () => {
    setIsCommentSidebarOpen(false);
    setCommentVideoId(null); // Clear the video ID when closing
  };
  // --- End Comment Sidebar Handlers ---

  if (!videos || videos.length === 0) {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-black text-white">
        <p className="text-lg">No videos available.</p>
      </div>
    );
  }

  return (
    <>
      <div className="bg-black h-screen w-full relative">
        {/* Notification Bell - Fixed in top right (Placeholder) */}
        {/* <div className="absolute top-4 right-4 z-20">
          <NotificationBell count={3} />
        </div> */}

        {/* Videos Container - Full screen, vertical scroll, snap mandatory */}
        <div
          ref={scrollContainerRef}
          className="h-screen w-screen overflow-y-scroll snap-y snap-mandatory scrollbar-hide bg-black"
        >
          {videos.map((video, index) => (
            // Each video container occupies full screen height and snaps into view
            <div
              id={`video-container-${video.video_id}`}
              key={video.video_id || `video-${index}`}
              className="h-screen w-screen snap-start flex justify-center items-center relative" // Added relative positioning
            >
              {/* Horizontal container for video and action bar */}
              <div className="flex items-end justify-center gap-4 relative h-[calc(100vh-80px)] max-h-[800px]">
                {" "}
                {/* Adjust positioning and height */}
                {/* Inner container to constrain video width and center it */}
                <div className="relative h-full w-auto max-w-[calc((100vh-80px)*(9/16))] aspect-[9/16] rounded-lg overflow-hidden bg-gray-900 shadow-lg">
                  {" "}
                  {/* Use aspect ratio */}
                  <VideoPlayer
                    videoInfo={video}
                    isActive={activeVideoId === video.video_id}
                  />
                  {/* Video Info Overlay (Example from VideoCard - integrate if needed)
                  <div className="absolute bottom-20 left-4 z-10 text-white p-3 rounded-lg bg-black/40 backdrop-blur-sm max-w-[70%]">
                    <h3 className="text-lg font-semibold mb-1">@{video.uploader_name || "Unknown Creator"}</h3>
                    <p className="text-sm text-gray-200 opacity-90">ID: {video.video_id.substring(0, 8)}...</p>
                  </div> */}
                </div>
                {/* Video Actions Bar - positioned vertically to the right */}
                <div className="flex-shrink-0 flex flex-col justify-end pb-16">
                  {" "}
                  {/* Adjust positioning */}
                  <VideoActionsBar
                    videoId={video.video_id}
                    commentCount={video.comment_count} // Pass comment count
                    onCommentClick={handleOpenComments} // Pass the open handler
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Render Comment Sidebar Conditionally - Outside the scroll container */}
      {/* Ensure commentVideoId is not null before rendering */}
      {commentVideoId && (
        <CommentSidebar
          isOpen={isCommentSidebarOpen}
          onClose={handleCloseComments}
          videoId={commentVideoId}
          // Optionally find the comment count for the specific video:
          // commentCount={videos.find(v => v.video_id === commentVideoId)?.comment_count ?? 0}
        />
      )}
    </>
  );
};

export default VideoFeed;
