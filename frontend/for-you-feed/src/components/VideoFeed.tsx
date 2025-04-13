"use client";

import { useState } from "react";
import { VideoInfo } from "@/app/types";
import VideoPlayer from "./VideoPlayer"; // We'll create this component next
import NotificationBell from "./NotificationBell";

interface VideoFeedProps {
  initialVideos: VideoInfo[];
}

/**
 * Client component for handling the TikTok-style vertical video feed
 * Uses CSS Scroll Snap for smooth snapping between videos
 */
const VideoFeed = ({ initialVideos }: VideoFeedProps) => {
  // In a real app, you might fetch more videos on scroll, but
  // for this example, we'll just use the initial set
  const [videos] = useState<VideoInfo[]>(initialVideos);

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
      <div className="h-screen w-screen overflow-y-scroll snap-y snap-mandatory scrollbar-hide bg-black">
        {videos.map((video, index) => (
          // Each video container occupies full screen height and snaps into view
          <div
            key={video.video_id || `video-${index}`}
            className="h-screen w-screen snap-start flex justify-center items-center"
          >
            {/* Inner container to constrain video width and center it */}
            <div className="relative h-[90vh] max-w-sm w-full aspect-[9/16]">
              <VideoPlayer videoInfo={video} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default VideoFeed;
