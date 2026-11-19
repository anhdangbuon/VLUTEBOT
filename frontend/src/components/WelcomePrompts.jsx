import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Lightbulb, RefreshCw } from "lucide-react";

const FM_EASE_OUT = [0.22, 1, 0.36, 1];
const FM_SPRING = { type: "spring", stiffness: 360, damping: 28 };

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
      delayChildren: 0.03,
    },
  },
  exit: {
    opacity: 0,
    y: -6,
    transition: { duration: 0.16, ease: FM_EASE_OUT },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 12, scale: 0.975 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.36, ease: FM_EASE_OUT },
  },
};

export default function WelcomePrompts({
  prompts,
  shuffleCount,
  isShuffling,
  onShuffle,
  onSelectPrompt,
}) {
  if (!Array.isArray(prompts) || prompts.length === 0) {
    return null;
  }

  return (
    <section className="mt-4 mb-6 w-full" aria-label="Gợi ý câu hỏi nhanh">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 mb-3">
        <div className="inline-flex items-center gap-1.5 text-[0.88rem] md:text-[0.92rem] font-bold text-[#00703c]">
          <Lightbulb className="w-[15px] h-[15px] text-[#00703c] shrink-0" strokeWidth={2.2} />
          <span>Gợi ý câu hỏi nhanh dành cho bạn:</span>
        </div>

        <motion.button
          type="button"
          data-testid="shuffle-prompts-btn"
          disabled={isShuffling}
          onClick={onShuffle}
          whileHover={{ y: -2, transition: FM_SPRING }}
          whileTap={{ scale: 0.97, transition: { duration: 0.12 } }}
          className="inline-flex items-center justify-center gap-1.5 px-3.5 py-1.5 rounded-[18px] bg-white text-[#00703c] border-[1.5px] border-[#00703c] text-[0.82rem] font-semibold shadow-[0_2px_4px_rgba(0,112,60,0.08)] hover:bg-[#00703c] hover:text-white hover:shadow-[0_6px_16px_rgba(0,112,60,0.22)] transition-colors duration-200 disabled:opacity-60 self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isShuffling ? "animate-spin" : ""}`} strokeWidth={2.2} />
          <span>Đổi 4 gợi ý khác</span>
        </motion.button>
      </div>

      <AnimatePresence mode="popLayout" initial={true}>
        <motion.div
          key={`welcome-grid-${shuffleCount}`}
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="grid grid-cols-1 sm:grid-cols-2 gap-2.5"
        >
          {prompts.slice(0, 4).map((item, idx) => (
            <motion.button
              key={`${shuffleCount}-${idx}-${item.query}`}
              type="button"
              data-testid="welcome-prompt-card"
              variants={itemVariants}
              whileHover={{ y: -2, transition: FM_SPRING }}
              whileTap={{ scale: 0.97, transition: { duration: 0.12 } }}
              onClick={() => onSelectPrompt(item.query)}
              className="w-full text-left bg-white text-[#00703c] border-[1.5px] border-[#00703c] rounded-[14px] md:rounded-[18px] px-3.5 py-2.5 text-[0.8rem] md:text-[0.83rem] font-semibold leading-[1.38] shadow-[0_2px_4px_rgba(0,112,60,0.08)] hover:bg-[#00703c] hover:text-white hover:shadow-[0_6px_16px_rgba(0,112,60,0.22)] transition-colors duration-200 cursor-pointer"
            >
              {item.label}
            </motion.button>
          ))}
        </motion.div>
      </AnimatePresence>
    </section>
  );
}
