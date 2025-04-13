"use client"; // Needed for onClick handler on the button

import React from "react";

// Define Props
type VideoActionsBarProps = {
  videoId: string;
  // Add other potential props like comment count later
  commentCount?: number;
  onCommentClick: (videoId: string) => void; // Callback function when comment icon is clicked
};

// Reusable Icon Component for Clarity
// ... existing code ...

const VideoActionsBar: React.FC<VideoActionsBarProps> = ({
  videoId,
  commentCount,
  onCommentClick, // Destructure the new prop
}) => {
  const handleCommentClick = () => {
    console.log(`Comment button clicked for video ${videoId}`);
    // Call the passed-in handler
    onCommentClick(videoId);
    // TODO: Implement actual comment functionality (e.g., open modal/panel) -> Handled by parent now
  };

  // Keyboard handler for accessibility
  // ... existing code ...
};
