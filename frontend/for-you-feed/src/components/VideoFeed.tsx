"use client";

import { useState, useRef, useEffect } from "react";
import { VideoInfo } from "@/app/types";
import VideoPlayer from "./VideoPlayer";
import NotificationBell from "./NotificationBell";

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
  const [activeVideoId, setActiveVideoId] = useState<string | null>(null);
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

  if (!videos || videos.length === 0) {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-black text-white">
        <p className="text-lg">No videos available.</p>
      </div>
    );
  }

  return (
    <div className="bg-black h-screen w-full relative">
      {/* Notification Bell - Fixed in top right */}
      <div className="absolute top-4 right-4 z-20">
        <NotificationBell count={3} />
      </div>

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
            className="h-screen w-screen snap-start flex justify-center items-center"
          >
            {/* Inner container to constrain video width and center it */}
            <div className="relative h-[90vh] max-w-sm w-full aspect-[9/16]">
              <VideoPlayer
                videoInfo={video}
                isActive={activeVideoId === video.video_id}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default VideoFeed;
