"use client";

import React, { useState, useRef, useEffect } from "react";
import { VideoInfo } from "@/app/types";
import VideoPlayer from "./VideoPlayer";
// import NotificationBell from "./NotificationBell";
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
  const [videos] = useState<VideoInfo[]>(initialVideos);
  // Track which video is currently active/visible
  const [activeVideoId, setActiveVideoId] = useState<string | null>(null);

  // State for comment sidebar
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

    // Auto-play the first video when the component mounts
    if (videos.length > 0 && !activeVideoId) {
      setActiveVideoId(videos[0].video_id);
    }

    // Cleanup when component unmounts
    return () => {
      observers.current.forEach((observer) => observer.disconnect());
      observers.current.clear();
    };
  }, [videos, activeVideoId]);

  // Comment sidebar handlers
  const handleOpenComments = (videoId: string) => {
    setCommentVideoId(videoId);
    setIsCommentSidebarOpen(true);
  };

  const handleCloseComments = () => {
    setIsCommentSidebarOpen(false);
    // Don't clear commentVideoId immediately to allow for exit animation
    setTimeout(() => {
      if (!isCommentSidebarOpen) {
        setCommentVideoId(null);
      }
    }, 300); // Match the transition duration
  };

  if (!videos || videos.length === 0) {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-black text-white">
        <p className="text-lg">No videos available.</p>
      </div>
    );
  }

  // For demo purposes, ensure videos have comment_count
  const videosWithComments = videos.map((video) => ({
    ...video,
    comment_count: video.comment_count || 0,
  }));

  return (
    <React.Fragment>
      <div className="bg-black h-screen w-full relative">
        {/* Notification Bell - Fixed in top right */}
        <div className="absolute top-4 right-4 z-20">
          {/* future feature */}
          {/* <NotificationBell count={3} /> */}
        </div>

        {/* Videos Container - Full screen, vertical scroll, snap mandatory */}
        <div
          ref={scrollContainerRef}
          className="h-screen w-screen overflow-y-scroll snap-y snap-mandatory scrollbar-hide bg-black"
        >
          {videosWithComments.map((video, index) => (
            // Each video container occupies full screen height and snaps into view
            <div
              id={`video-container-${video.video_id}`}
              key={video.video_id || `video-${index}`}
              className="relative h-screen w-screen snap-start flex justify-center items-center overflow-hidden"
            >
              {/* Horizontal container for video and action bar */}
              <div className="h-full w-full flex items-center justify-center">
                {/* Inner container to constrain video width and center it */}
                <div className="relative w-full max-w-2xs md:max-w-xs lg:max-w-sm aspect-[9/16] max-h-full">
                  <VideoPlayer
                    videoInfo={video}
                    isActive={activeVideoId === video.video_id}
                  />
                </div>

                {/* Video Actions Bar - positioned to the right of the video */}
                <div className="flex-shrink-0 ml-3">
                  <VideoActionsBar
                    videoId={video.video_id}
                    commentCount={video.comment_count}
                    onCommentClick={handleOpenComments}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Render the Comment Sidebar - Conditionally to ensure clean unmounting */}
      {commentVideoId && (
        <CommentSidebar
          isOpen={isCommentSidebarOpen}
          onClose={handleCloseComments}
          videoId={commentVideoId}
          commentCount={
            videos.find((v) => v.video_id === commentVideoId)?.comment_count ||
            0
          }
        />
      )}
    </React.Fragment>
  );
};

export default VideoFeed;
