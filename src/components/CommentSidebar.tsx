"use client";

import React, { useState, useEffect, FormEvent } from "react";
import { Comment } from "@/app/types"; // Adjust path if necessary

// Define Props
interface CommentSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  videoId: string; // To know which video comments belong to
  // commentCount: number; // Optional: passed from VideoActionsBar if available
}

// Reusable Close Icon Component
const CloseIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className="size-6"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M6 18 18 6M6 6l12 12"
    />
  </svg>
);

// Reusable Send Icon for Post Button
const SendIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    className="size-5"
  >
    <path d="M3.478 2.404a.75.75 0 0 0-.926.941l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.404Z" />
  </svg>
);

const CommentSidebar: React.FC<CommentSidebarProps> = ({
  isOpen,
  onClose,
  videoId,
  // commentCount = 0,
}) => {
  const [commentText, setCommentText] = useState("");
  // State to hold optimistically added comments
  const [submittedComments, setSubmittedComments] = useState<Comment[]>([]);

  // TODO: Later, fetch actual comments for the videoId when the sidebar opens
  useEffect(() => {
    if (isOpen) {
      console.log(`Comment sidebar opened for video: ${videoId}`);
      // Fetch comments logic would go here
      // For now, clear optimistic comments when switching videos or reopening
      setSubmittedComments([]);
    }
  }, [isOpen, videoId]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setCommentText(e.target.value);
  };

  const handleSubmitComment = (e: FormEvent) => {
    e.preventDefault(); // Prevent default form submission
    if (!commentText.trim()) return; // Don't submit empty comments

    const newComment: Comment = {
      id: `temp-${Date.now()}-${Math.random()}`, // Temporary unique ID for optimistic update
      videoId: videoId,
      author: "You", // Placeholder - replace with actual user later
      text: commentText.trim(),
      timestamp: new Date(),
    };

    // Optimistic update: Add comment immediately to the UI
    setSubmittedComments((prev) => [...prev, newComment]);
    setCommentText(""); // Clear the input field

    console.log("Submitting comment:", newComment);
    // TODO: Send the comment to the backend API
    // try {
    //   await fetch('/api/comments', {
    //     method: 'POST',
    //     headers: { 'Content-Type': 'application/json' },
    //     body: JSON.stringify({ videoId, text: newComment.text }),
    //   });
    //   // Optionally refetch comments or handle success/error
    // } catch (error) {
    //   console.error("Failed to submit comment:", error);
    //   // Handle error: remove optimistic comment or show error message
    //   setSubmittedComments(prev => prev.filter(c => c.id !== newComment.id));
    // }
  };

  // Keyboard handler for closing with Escape key
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
    }

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  return (
    // Overlay to capture clicks outside the sidebar
    <div
      className={`fixed inset-0 z-30 transition-opacity duration-300 ease-in-out ${
        isOpen ? "bg-black/30" : "bg-transparent pointer-events-none"
      }`}
      onClick={onClose} // Close when clicking overlay
      aria-hidden={!isOpen}
    >
      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 right-0 h-full w-full max-w-md bg-gray-900 shadow-xl transform transition-transform duration-300 ease-in-out flex flex-col ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        onClick={(e) => e.stopPropagation()} // Prevent closing when clicking inside sidebar
        role="dialog"
        aria-modal="true"
        aria-labelledby="comment-sidebar-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700 flex-shrink-0">
          <h2 id="comment-sidebar-title" className="text-lg font-semibold">
            Comments{" "}
            {/* Placeholder for dynamic count: ({commentCount + submittedComments.length}) */}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close comments sidebar"
            className="text-gray-400 hover:text-white focus:outline-none focus:ring-2 focus:ring-white rounded-full p-1"
            tabIndex={0}
          >
            <CloseIcon />
          </button>
        </div>

        {/* Comment List - Scrollable */}
        <div className="flex-grow overflow-y-auto p-4 space-y-4">
          {submittedComments.length === 0 ? (
            <p className="text-gray-400 text-center mt-4">No comments yet.</p>
          ) : (
            submittedComments.map((comment) => (
              <div key={comment.id} className="flex items-start space-x-3">
                {/* Placeholder for avatar */}
                <div className="w-8 h-8 rounded-full bg-gray-600 flex-shrink-0 mt-1"></div>
                <div>
                  <p className="text-sm font-semibold">{comment.author}</p>
                  <p className="text-sm text-gray-200">{comment.text}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {comment.timestamp.toLocaleTimeString([], {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
              </div>
            ))
          )}
          {/* Add loading indicator here if fetching real comments */}
        </div>

        {/* Comment Input Form - Fixed at bottom */}
        <div className="p-4 border-t border-gray-700 flex-shrink-0 bg-gray-900">
          <form
            onSubmit={handleSubmitComment}
            className="flex items-center space-x-2"
          >
            <textarea
              value={commentText}
              onChange={handleInputChange}
              placeholder="Add comment..."
              aria-label="Add a comment"
              rows={1} // Start with 1 row, auto-expand if needed (can add JS for this)
              className="flex-grow bg-gray-800 border border-gray-700 rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none text-sm scrollbar-hide"
            />
            <button
              type="submit"
              disabled={!commentText.trim()} // Disable if input is empty
              aria-label="Post comment"
              className={`p-2 rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors ${
                commentText.trim()
                  ? "bg-blue-600 hover:bg-blue-700 text-white"
                  : "bg-gray-700 text-gray-500 cursor-not-allowed"
              }`}
            >
              <SendIcon />
            </button>
          </form>
        </div>
      </aside>
    </div>
  );
};

export default CommentSidebar;
