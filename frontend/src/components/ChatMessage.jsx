import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Lightbulb } from "lucide-react";
import ReactMarkdown from "react-markdown";
import ContactCard from "./ContactCard.jsx";

const FM_EASE_OUT = [0.22, 1, 0.36, 1];
const FM_SPRING = { type: "spring", stiffness: 360, damping: 28 };

export default function ChatMessage({
  message,
  avatarUrl,
  isLatestAssistant,
  onSelectFollowup,
  isGlobalStreaming,
}) {
  if (message.role === "user") {
    return (
      <motion.div
        data-testid="chat-row-user"
        initial={{ opacity: 0.72, y: 8, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.26, ease: FM_EASE_OUT }}
        className="flex justify-end w-full mb-[1.15rem] pl-0 md:pl-12"
      >
        <div
          data-testid="user-bubble"
          className="bg-[#0073b7] border-2 border-[#005587] text-white rounded-[20px] px-3.5 py-2.5 md:px-5 md:py-3 max-w-[92%] md:max-w-[720px] w-fit whitespace-pre-wrap break-words text-[0.92rem] md:text-[1rem] leading-[1.6] shadow-[0_4px_14px_rgba(0,115,183,0.18)]"
        >
          {message.content}
        </div>
      </motion.div>
    );
  }

  const isBusy = Boolean(message.isThinking || message.isStreaming);
  const showFollowups =
    !message.isWelcome &&
    isLatestAssistant &&
    !message.isStreaming &&
    !message.isThinking &&
    Array.isArray(message.followups) &&
    message.followups.length > 0;

  return (
    <motion.div
      data-testid="chat-row-assistant"
      initial={{ opacity: 0.72, y: 8, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.26, ease: FM_EASE_OUT }}
      className="flex items-start gap-2.5 md:gap-3.5 w-full mb-[1.15rem]"
    >
      <div className="shrink-0 w-[34px] h-[34px] md:w-[48px] md:h-[48px] mt-0.5 rounded-full">
        <img
          src={avatarUrl || "/assets/lucas_avatar.png"}
          alt="Lucas"
          width={48}
          height={48}
          className={`w-[34px] h-[34px] md:w-[48px] md:h-[48px] rounded-full object-cover shadow-[0_2px_6px_rgba(0,0,0,0.15)] ${
            isBusy ? "avatar-pulse" : ""
          }`}
        />
      </div>

      <div className="flex-1 min-w-0 max-w-[92%] md:max-w-[720px]">
        <div
          data-testid="assistant-bubble"
          className="bg-white border-[1.5px] border-[#cbd5e1] border-l-4 border-l-[#00703c] rounded-[20px] px-3.5 py-2.5 md:px-5 md:py-3.5 w-fit max-w-full min-h-[54px] text-[#1e293b] shadow-[0_4px_14px_rgba(0,112,60,0.12)] transition-shadow duration-200"
        >
          {message.isThinking && !message.content ? (
            <div
              data-testid="typing-indicator"
              aria-label="Lucas đang soạn câu trả lời"
              className="flex items-center gap-2.5 min-h-[28px] py-0.5"
            >
              <div className="inline-flex items-center gap-[5px]">
                <span className="typing-dot typing-dot-1" />
                <span className="typing-dot typing-dot-2" />
                <span className="typing-dot typing-dot-3" />
              </div>
              <span className="text-[0.88rem] text-[#00703c] italic font-medium whitespace-nowrap">
                Lucas đang tra cứu quy chế VLUTE...
              </span>
            </div>
          ) : (
            <>
              <AnimatePresence initial={true}>
                {message.verified && (
                  <motion.div
                    key="verify-badge"
                    data-testid="verify-badge"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.22, ease: FM_EASE_OUT }}
                    className="inline-flex items-center bg-[#e8f5e9] text-[#2e7d32] text-[13px] font-semibold px-3 py-1 rounded-[16px] mb-2"
                  >
                    {message.elapsedTime != null
                      ? `✅ Đã đối soát thành công (${message.elapsedTime}s) - Được trích từ quy chế liên quan`
                      : "✅ Đã đối soát thành công - Được trích từ quy chế liên quan"}
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="vlute-markdown">
                <ReactMarkdown
                  components={{
                    a: ({ node, ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    ),
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              </div>

              {message.contact && (
                <ContactCard
                  contact={message.contact}
                  disableAnimation={Boolean(message.isWelcome)}
                />
              )}
            </>
          )}
        </div>

        <AnimatePresence initial={true}>
          {showFollowups && (
            <motion.div
              key={`followups-${message.id}`}
              data-testid="followup-container"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{
                opacity: 0,
                y: -4,
                height: 0,
                marginTop: 0,
                overflow: "hidden",
                transition: { duration: 0.14, ease: FM_EASE_OUT },
              }}
              transition={{ duration: 0.28, ease: FM_EASE_OUT }}
              className="mt-2.5 w-full"
            >
              <p className="text-[0.85rem] md:text-[0.88rem] text-[#00703c] font-bold mb-1.5 flex items-center gap-1.5">
                <Lightbulb className="w-[15px] h-[15px] text-[#00703c] shrink-0" strokeWidth={2.2} />
                <span>Gợi ý câu hỏi liên quan bạn có thể quan tâm:</span>
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 min-h-[46px]">
                {message.followups.map((item, fIdx) => (
                  <motion.button
                    key={`${message.id}-fu-${fIdx}-${item.query}`}
                    type="button"
                    data-testid="followup-btn"
                    disabled={isGlobalStreaming}
                    whileHover={{ y: -2, transition: FM_SPRING }}
                    whileTap={{ scale: 0.97, transition: { duration: 0.12 } }}
                    onClick={() => onSelectFollowup(item.query)}
                    className="w-full text-left bg-white text-[#00703c] border-[1.5px] border-[#00703c] rounded-[14px] md:rounded-[18px] px-3 py-2 text-[0.78rem] md:text-[0.82rem] font-semibold leading-[1.35] shadow-[0_2px_4px_rgba(0,112,60,0.08)] hover:bg-[#00703c] hover:text-white hover:shadow-[0_6px_16px_rgba(0,112,60,0.22)] transition-colors duration-200 disabled:opacity-50 cursor-pointer"
                  >
                    {item.label}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
