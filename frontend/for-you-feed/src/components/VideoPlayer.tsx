"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { VideoInfo } from "@/app/types";
import { PlayIcon, PauseIcon } from "@heroicons/react/24/solid";

/**
 * Formats seconds into MM:SS format with leading zeros
 */
const formatTime = (seconds: number): string => {
  if (isNaN(seconds) || seconds < 0) return "00:00";

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  return `${minutes.toString().padStart(2, "0")}:${remainingSeconds
    .toString()
    .padStart(2, "0")}`;
};

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
  const progressBarRef = useRef<HTMLDivElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  // Show play icon briefly on pause/initial load
  const [showPlayIcon, setShowPlayIcon] = useState(true);
  const [showPauseIcon, setShowPauseIcon] = useState(false);
  const playIconTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pauseIconTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // New state for enhanced progress bar
  const [isHoveringProgressBar, setIsHoveringProgressBar] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [showTimestamp, setShowTimestamp] = useState(false);
  const [timestampText, setTimestampText] = useState("00:00 / 00:00");
  const [scrubberPositionX, setScrubberPositionX] = useState(0);
  const [videoDuration, setVideoDuration] = useState(0);
  const timestampTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const wasPlayingBeforeDragRef = useRef(false);

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

    // Update scrubber position if we're not currently dragging
    if (!isDragging && isHoveringProgressBar) {
      setScrubberPositionX(currentProgress * 100);
    }
  }, [isDragging, isHoveringProgressBar]); // Dependencies for the scrubber position updates

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

  const handleVideoMetadataLoaded = useCallback(() => {
    if (videoRef.current && !isNaN(videoRef.current.duration)) {
      setVideoDuration(videoRef.current.duration);
    }
  }, []);

  // Show/hide timestamp with auto-hide timer
  const showTimestampWithTimeout = useCallback(
    (positionX: number, currentTime: number) => {
      if (timestampTimeoutRef.current) {
        clearTimeout(timestampTimeoutRef.current);
        timestampTimeoutRef.current = null;
      }

      const formattedCurrentTime = formatTime(currentTime);
      const formattedTotalTime = formatTime(videoDuration);
      setTimestampText(`${formattedCurrentTime} / ${formattedTotalTime}`);
      setShowTimestamp(true);

      // Auto-hide after 500ms, unless we're dragging
      if (!isDragging) {
        timestampTimeoutRef.current = setTimeout(() => {
          setShowTimestamp(false);
        }, 500);
      }
    },
    [videoDuration, isDragging]
  );

  // Click handler for the progress bar to seek
  const handleSeek = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (
        !videoRef.current ||
        !videoRef.current.duration ||
        isNaN(videoRef.current.duration) ||
        !progressBarRef.current
      ) {
        return; // Video not ready or duration unknown
      }

      // If we just finished dragging, don't trigger another seek
      if (event.type === "click" && isDragging) {
        return;
      }

      event.stopPropagation(); // Prevent triggering play/pause on the parent

      const progressBar = progressBarRef.current;
      const rect = progressBar.getBoundingClientRect();
      const clickX = event.clientX - rect.left;
      const barWidth = rect.width;

      if (barWidth > 0) {
        const seekFraction = Math.max(0, Math.min(1, clickX / barWidth));
        const targetTime = seekFraction * videoRef.current.duration;
        videoRef.current.currentTime = targetTime;

        // Update progress state immediately for better UI feedback
        setProgress(seekFraction);
        setScrubberPositionX(seekFraction * 100);

        // Show timestamp
        showTimestampWithTimeout(seekFraction * 100, targetTime);
      }
    },
    [showTimestampWithTimeout]
  );

  // Progress bar hover handlers
  const handleProgressBarMouseEnter = useCallback(() => {
    setIsHoveringProgressBar(true);
    if (videoRef.current) {
      const currentTime = videoRef.current.currentTime;
      const duration = videoRef.current.duration || 0;
      if (duration > 0) {
        setScrubberPositionX((currentTime / duration) * 100);
      }
    }
  }, []);

  const handleProgressBarMouseLeave = useCallback(() => {
    if (!isDragging) {
      setIsHoveringProgressBar(false);
      if (!showTimestamp) {
        // If we're not showing the timestamp (or it's about to hide), we can hide the scrubber too
        // This prevents the scrubber from disappearing while the timestamp is still visible
        setScrubberPositionX(-1); // Use a negative value to hide it via CSS
      }
    }
  }, [isDragging, showTimestamp]);

  // Progress bar drag handlers
  const handleProgressBarMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!videoRef.current || !progressBarRef.current) return;

      // Prevent default to avoid text selection during drag
      event.preventDefault();

      // Store current playing state
      wasPlayingBeforeDragRef.current = isPlaying;
      if (isPlaying && videoRef.current) {
        videoRef.current.pause();
      }

      setIsDragging(true);

      // Calculate initial position
      const progressBar = progressBarRef.current;
      const rect = progressBar.getBoundingClientRect();
      const clickX = event.clientX - rect.left;
      const barWidth = rect.width;

      if (barWidth > 0) {
        const seekFraction = Math.max(0, Math.min(1, clickX / barWidth));
        const targetTime = seekFraction * videoRef.current.duration;

        // Update UI immediately
        setProgress(seekFraction);
        setScrubberPositionX(seekFraction * 100);

        // Show timestamp
        showTimestampWithTimeout(seekFraction * 100, targetTime);

        // Update video time for live preview
        videoRef.current.currentTime = targetTime;
      }
    },
    [isPlaying, showTimestampWithTimeout]
  );

  // Handle mouse move during drag (attached to window)
  const handleMouseMove = useCallback(
    (event: MouseEvent) => {
      if (!isDragging || !progressBarRef.current || !videoRef.current) return;

      const progressBar = progressBarRef.current;
      const rect = progressBar.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const barWidth = rect.width;

      if (barWidth > 0) {
        const seekFraction = Math.max(0, Math.min(1, mouseX / barWidth));
        const targetTime = seekFraction * videoRef.current.duration;

        // Update UI
        setProgress(seekFraction);
        setScrubberPositionX(seekFraction * 100);

        // Update timestamp without auto-hide
        const formattedCurrentTime = formatTime(targetTime);
        const formattedTotalTime = formatTime(videoDuration);
        setTimestampText(`${formattedCurrentTime} / ${formattedTotalTime}`);
        setShowTimestamp(true);

        // Live preview
        videoRef.current.currentTime = targetTime;
      }
    },
    [isDragging, videoDuration]
  );

  // Handle mouse up to end dragging (attached to window)
  const handleMouseUp = useCallback(() => {
    if (!isDragging || !videoRef.current) return;

    setIsDragging(false);

    // Resume playback if it was playing before
    if (wasPlayingBeforeDragRef.current) {
      videoRef.current
        .play()
        .then(() => {
          setIsPlaying(true);
        })
        .catch((error) => {
          console.error("Failed to resume playback after drag:", error);
          setIsPlaying(false);
        });
    }

    // Start the auto-hide timer for timestamp
    if (timestampTimeoutRef.current) {
      clearTimeout(timestampTimeoutRef.current);
    }
    timestampTimeoutRef.current = setTimeout(() => {
      setShowTimestamp(false);

      // Hide scrubber after timestamp if not hovering
      if (!isHoveringProgressBar) {
        setScrubberPositionX(-1);
      }
    }, 500);
  }, [isDragging, isHoveringProgressBar]);

  // Effect to set up global mouse event listeners for dragging
  useEffect(() => {
    if (isDragging) {
      // Add global event listeners
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }

    // Cleanup
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

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

  // Load metadata and set up video event listeners
  useEffect(() => {
    const videoElement = videoRef.current;
    if (!videoElement) return;

    // Set up listeners
    videoElement.addEventListener("loadedmetadata", handleVideoMetadataLoaded);

    // If metadata is already loaded, call the handler directly
    if (videoElement.readyState >= 2) {
      handleVideoMetadataLoaded();
    }

    return () => {
      videoElement.removeEventListener(
        "loadedmetadata",
        handleVideoMetadataLoaded
      );
    };
  }, [handleVideoMetadataLoaded]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (playIconTimeoutRef.current) clearTimeout(playIconTimeoutRef.current);
      if (pauseIconTimeoutRef.current)
        clearTimeout(pauseIconTimeoutRef.current);
      if (timestampTimeoutRef.current)
        clearTimeout(timestampTimeoutRef.current);
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
      className="relative w-full h-full bg-black rounded-lg cursor-pointer group focus:outline-none"
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
        className="w-full h-full object-cover overflow-hidden"
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
      <div
        className={`absolute bottom-8 left-4 text-white text-shadow pointer-events-none select-none transition-opacity duration-150 ${
          showTimestamp ? "opacity-0" : "opacity-100"
        }`}
      >
        <p className="font-semibold text-base drop-shadow-md">
          @
          {extractUsernameFromVideoId(videoInfo.video_id) ||
            videoInfo.uploader_name ||
            "Unknown Creator"}
        </p>
      </div>

      {/* Enhanced Progress Bar Container */}
      <div
        ref={progressBarRef}
        className="absolute bottom-0 left-0 w-full h-[6px] cursor-pointer group pointer-events-auto"
        onClick={handleSeek}
        onMouseEnter={handleProgressBarMouseEnter}
        onMouseLeave={handleProgressBarMouseLeave}
        onMouseDown={handleProgressBarMouseDown}
        role="slider"
        aria-label="Video progress"
        aria-valuemin={0}
        aria-valuemax={Math.round(videoDuration)}
        aria-valuenow={
          videoRef.current ? Math.round(videoRef.current.currentTime) : 0
        }
        aria-valuetext={timestampText}
      >
        {/* Unplayed Track (Background) */}
        <div className="absolute left-0 top-0 w-full h-full bg-gray-200 bg-opacity-40 rounded-sm" />

        {/* Played Track */}
        <div
          className="absolute left-0 top-0 h-full bg-red-500 rounded-sm transition-all duration-100 ease-linear"
          style={{ width: `${progress * 100}%` }}
        />

        {/* Timestamp Display */}
        <div
          className={`absolute bottom-[calc(100%+24px)] left-1/2 -translate-x-1/2 py-1 text-white text-2xl font-semibold drop-shadow-lg transition-opacity duration-150 ease-out ${
            showTimestamp ? "opacity-100" : "opacity-0"
          }`}
        >
          {timestampText}
        </div>

        {/* Scrubber Handle */}
        <div
          className={`absolute top-1/2 w-3 h-3 bg-white rounded-full shadow-md z-10 transition-opacity transition-transform duration-100 ease-out ${
            scrubberPositionX >= 0 &&
            (isHoveringProgressBar || isDragging || showTimestamp)
              ? "opacity-100 scale-100"
              : "opacity-0 scale-75"
          }`}
          style={{
            left: `${scrubberPositionX}%`,
            transform: `translate(-50%, -50%)`,
          }}
        />
      </div>
    </div>
  );
};

export default VideoPlayer;
