"use client";

import React, { useState, useEffect, FormEvent } from "react";
import { Comment } from "@/app/types";

// Define Props
interface CommentSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  videoId: string; // To know which video comments belong to
  commentCount?: number; // Optional: passed from VideoActionsBar if available
}

// Reusable Close Icon Component
const CloseIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className="size-5"
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
  commentCount = 0,
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
    setSubmittedComments((prev) => [newComment, ...prev]); // Add to beginning of array
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

  // Handle Enter/Return key to submit comment
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault(); // Prevent newline
      if (commentText.trim()) {
        handleSubmitComment(e as unknown as FormEvent);
      }
    }
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
    // No overlay - use a fixed sidebar that doesn't affect video brightness
    <>
      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 right-0 h-full w-full max-w-md bg-black shadow-xl transform transition-transform duration-300 ease-in-out flex flex-col z-50 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        onClick={(e) => e.stopPropagation()} // Prevent closing when clicking inside sidebar
        role="dialog"
        aria-modal="true"
        aria-labelledby="comment-sidebar-title"
      >
        {/* Header - Close button moved to right side */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 flex-shrink-0">
          <h2
            id="comment-sidebar-title"
            className="text-lg font-semibold text-white"
          >
            Comments
            {commentCount > 0 && (
              <span className="ml-2 text-gray-400">
                {commentCount + submittedComments.length}
              </span>
            )}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close comments sidebar"
            className="text-white hover:text-gray-300 focus:outline-none p-1"
            tabIndex={0}
          >
            <CloseIcon />
          </button>
        </div>

        {/* Comment List - Scrollable with improved spacing */}
        <div className="flex-grow overflow-y-auto pt-5 pb-4 scrollbar-hide">
          {submittedComments.length === 0 ? (
            <div className="text-gray-400 text-center py-12">
              <p className="text-base">No comments yet</p>
              <p className="text-sm mt-1">Be the first to comment!</p>
            </div>
          ) : (
            submittedComments.map((comment) => (
              <div
                key={comment.id}
                className="px-5 py-5 mb-2 hover:bg-gray-900/30"
              >
                <div className="flex items-start space-x-4">
                  {/* User Avatar */}
                  <div className="w-10 h-10 rounded-full bg-gray-700 flex-shrink-0 overflow-hidden">
                    {/* Placeholder for avatar - in a real app, this would be an image */}
                    <div className="w-full h-full flex items-center justify-center text-white font-bold">
                      {comment.author.charAt(0).toUpperCase()}
                    </div>
                  </div>

                  <div className="flex-1">
                    {/* Author and timestamp with improved spacing */}
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-semibold text-white">
                        {comment.author}
                      </p>
                      <p className="text-xs text-gray-500">
                        {comment.timestamp.toLocaleTimeString([], {
                          hour: "numeric",
                          minute: "2-digit",
                        })}
                      </p>
                    </div>

                    {/* Comment text with better spacing */}
                    <p className="text-sm text-white mt-2 mb-3">
                      {comment.text}
                    </p>

                    {/* Comment actions - only Reply with reduced opacity */}
                    <div className="flex items-center">
                      <button className="text-xs text-gray-400 hover:text-white opacity-85 transition-colors duration-200">
                        Reply
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Comment Input Form - Fixed at bottom with Post button inside */}
        <div className="px-4 pt-3 pb-4 border-t border-gray-800 flex-shrink-0 bg-black">
          <form
            onSubmit={handleSubmitComment}
            className="relative" // Relative to position the post button
          >
            <textarea
              value={commentText}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Add comment..."
              aria-label="Add a comment"
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 pr-14 focus:outline-none focus:border-gray-600 focus:ring-0 transition-colors duration-200 resize-none text-white text-sm placeholder-gray-500"
            />
            <button
              type="submit"
              disabled={!commentText.trim()}
              aria-label="Post comment"
              className={`absolute bottom-3 right-3 p-2 rounded-full transition-colors duration-200 ${
                commentText.trim()
                  ? "bg-white hover:bg-gray-200 text-black"
                  : "bg-gray-700 text-gray-500 cursor-not-allowed"
              }`}
            >
              <SendIcon />
            </button>
          </form>
        </div>
      </aside>

      {/* Invisible click handler behind the sidebar - only shows when sidebar is open */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
    </>
  );
};

export default CommentSidebar;
