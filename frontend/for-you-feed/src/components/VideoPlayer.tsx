"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { VideoInfo } from "@/app/types";
import { PlayIcon, PauseIcon } from "@heroicons/react/24/solid";

/**
 * Extracts username from video_id which has the format <username>-<tiktok_id>
 */
const extractUsernameFromVideoId = (videoId: string): string => {
  if (!videoId) return "Unknown Creator";
  const parts = videoId.split("-");
  return parts[0] || "Unknown Creator";
};

interface VideoPlayerProps {
  videoInfo: VideoInfo;
  isActive?: boolean;
}

/**
 * Represents a single video player within the feed.
 * Handles play/pause on click, progress bar, and info display.
 * Auto-pauses when not active in viewport and auto-plays when active.
 */
const VideoPlayer: React.FC<VideoPlayerProps> = ({
  videoInfo,
  isActive = false,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  // Show play icon briefly on pause/initial load
  const [showPlayIcon, setShowPlayIcon] = useState(true);
  const [showPauseIcon, setShowPauseIcon] = useState(false);
  const playIconTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pauseIconTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const triggerIconFade = (type: "play" | "pause") => {
    if (type === "play") {
      setShowPauseIcon(true);
      if (pauseIconTimeoutRef.current)
        clearTimeout(pauseIconTimeoutRef.current);
      pauseIconTimeoutRef.current = setTimeout(
        () => setShowPauseIcon(false),
        500
      ); // Show pause icon for 0.5s
    } else {
      setShowPlayIcon(true);
      if (playIconTimeoutRef.current) clearTimeout(playIconTimeoutRef.current);
      // Keep play icon visible when paused
    }
  };

  // Play/pause logic
  const handlePlayPause = useCallback(() => {
    if (!videoRef.current) return;

    const videoElement = videoRef.current;
    const currentlyPlaying = !videoElement.paused && !videoElement.ended;

    if (currentlyPlaying) {
      videoElement.pause();
      setIsPlaying(false);
      setShowPlayIcon(true); // Show play icon immediately when paused
      if (pauseIconTimeoutRef.current)
        clearTimeout(pauseIconTimeoutRef.current); // Clear any fade out for pause icon
      setShowPauseIcon(false); // Hide pause icon immediately
      triggerIconFade("pause");
    } else {
      videoElement
        .play()
        .then(() => {
          setIsPlaying(true);
          setShowPlayIcon(false); // Hide play icon immediately when playing
          if (playIconTimeoutRef.current)
            clearTimeout(playIconTimeoutRef.current); // Clear any fade out for play icon
          triggerIconFade("play");
        })
        .catch((error) => {
          console.error("Video play failed:", error);
          // Handle cases where autoplay might be blocked
          setIsPlaying(false);
          setShowPlayIcon(true);
        });
    }
  }, []); // No dependencies needed if only accessing refs and setting state

  const handleTimeUpdate = useCallback(() => {
    if (!videoRef.current || videoRef.current.duration === 0) return; // Avoid NaN
    const currentProgress =
      videoRef.current.currentTime / videoRef.current.duration;
    setProgress(currentProgress);
  }, []); // No dependency needed

  const handleVideoEnd = useCallback(() => {
    setIsPlaying(false);
    setProgress(1); // Show full bar briefly
    // Optional: Reset to 0 after a short delay or keep it full
    setTimeout(() => {
      setProgress(0);
      if (videoRef.current) {
        videoRef.current.currentTime = 0; // Reset video to start
      }
      setShowPlayIcon(true); // Show play icon when ended
    }, 300);
  }, []);

  // Click handler for the progress bar to seek
  const handleSeek = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (
      !videoRef.current ||
      !videoRef.current.duration ||
      isNaN(videoRef.current.duration)
    ) {
      return; // Video not ready or duration unknown
    }
    event.stopPropagation(); // Prevent triggering play/pause on the parent

    const progressBar = event.currentTarget;
    const clickX = event.nativeEvent.offsetX; // Position relative to the target element
    const barWidth = progressBar.offsetWidth;

    if (barWidth > 0) {
      const seekFraction = clickX / barWidth;
      const targetTime = seekFraction * videoRef.current.duration;
      videoRef.current.currentTime = targetTime;

      // Update progress state immediately for better UI feedback
      setProgress(seekFraction);
    }
  }, []); // Empty dependency array: only uses refs and doesn't depend on other state/props

  // Effect to automatically play or pause video based on isActive prop
  useEffect(() => {
    if (!videoRef.current) return;

    const videoElement = videoRef.current;

    if (isActive) {
      // This video is active/visible
      videoElement
        .play()
        .then(() => {
          setIsPlaying(true);
          setShowPlayIcon(false);
          triggerIconFade("play");
        })
        .catch((error) => {
          console.error("Auto-play failed:", error);
          setIsPlaying(false);
          setShowPlayIcon(true);
        });
    } else {
      // This video is not active/visible - pause it
      if (!videoElement.paused) {
        videoElement.pause();
        setIsPlaying(false);
        setShowPlayIcon(true);
      }
    }
  }, [isActive]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (playIconTimeoutRef.current) clearTimeout(playIconTimeoutRef.current);
      if (pauseIconTimeoutRef.current)
        clearTimeout(pauseIconTimeoutRef.current);
    };
  }, []);

  // Add keyboard support for play/pause (Spacebar)
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.code === "Space" || event.key === " ") {
        event.preventDefault(); // Prevent page scroll
        handlePlayPause();
      }
    },
    [handlePlayPause]
  );

  return (
    // Main container: relative for positioning children, rounded, overflow hidden, cursor pointer for interaction
    <div
      className="relative w-full h-full bg-black rounded-lg overflow-hidden cursor-pointer group focus:outline-none"
      onClick={handlePlayPause}
      onKeyDown={handleKeyDown}
      tabIndex={0} // Make it focusable for keyboard events
      role="button" // Semantics
      aria-label={isPlaying ? "Pause video" : "Play video"}
    >
      {/* Video Element */}
      <video
        ref={videoRef}
        src={videoInfo.video_url}
        // Ensures video covers the container, potentially cropping parts
        className="w-full h-full object-cover"
        loop={false} // Standard TikTok behavior is no loop
        onTimeUpdate={handleTimeUpdate}
        onEnded={handleVideoEnd}
        playsInline // Crucial for iOS and inline playback
        preload="metadata" // Good default: loads dimensions, duration, first frame
        aria-hidden="true" // Hide from accessibility tree as controls are handled by parent div
      />

      {/* Play Icon Overlay - Fades in/out */}
      <div
        className={`absolute inset-0 flex items-center justify-center transition-opacity duration-300 ease-in-out pointer-events-none ${
          showPlayIcon && !isPlaying ? "opacity-70" : "opacity-0"
        }`}
      >
        <PlayIcon className="w-16 h-16 text-white drop-shadow-lg" />
      </div>

      {/* Pause Icon Overlay - Fades in/out */}
      <div
        className={`absolute inset-0 flex items-center justify-center transition-opacity duration-300 ease-in-out pointer-events-none ${
          showPauseIcon && isPlaying ? "opacity-70" : "opacity-0"
        }`}
      >
        <PauseIcon className="w-16 h-16 text-white drop-shadow-lg" />
      </div>

      {/* Video Info Overlay */}
      <div className="absolute bottom-8 left-4 text-white text-shadow pointer-events-none select-none">
        <p className="font-semibold text-base drop-shadow-md">
          @
          {extractUsernameFromVideoId(videoInfo.video_id) ||
            videoInfo.uploader_name ||
            "Unknown Creator"}
        </p>
      </div>

      {/* Progress Bar - Now clickable */}
      <div
        className="absolute bottom-0 left-0 w-full h-[6px] bg-gray-200 bg-opacity-40 cursor-pointer pointer-events-auto"
        onClick={handleSeek}
        role="slider"
        aria-label="Video progress bar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <div
          className="h-full bg-red-500 transition-all duration-100 ease-linear pointer-events-none" // Inner bar should not capture clicks
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </div>
  );
};

export default VideoPlayer;
