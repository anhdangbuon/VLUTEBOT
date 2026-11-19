import React from "react";
import { motion } from "framer-motion";
import { BookOpen, Search, ShieldCheck } from "lucide-react";

const FM_EASE_OUT = [0.22, 1, 0.36, 1];

const BADGE_CONFIG = {
  search: {
    Icon: Search,
    className: "bg-[#008d4c] shadow-[0_2px_5px_rgba(0,141,76,0.18)]",
  },
  official: {
    Icon: BookOpen,
    className: "bg-[#e67e22] shadow-[0_2px_5px_rgba(230,126,34,0.18)]",
  },
  verified: {
    Icon: ShieldCheck,
    className: "bg-[#0073b7] shadow-[0_2px_5px_rgba(0,115,183,0.18)]",
  },
};

export default function HeroHeader({ branding }) {
  const title = branding?.title || "LUCAS – TRỢ LÝ QUY CHẾ & HỌC VỤ VLUTE";
  const subtitle =
    branding?.subtitle || "Hệ thống tra cứu từ văn bản chính thức của Nhà trường";
  const logoUrl = branding?.logo_url || "/assets/logo_vlute.png";
  const avatarUrl = branding?.avatar_url || "/assets/lucas_avatar.png";
  const badges = branding?.badges || [
    { id: "search", label: "Tra cứu học vụ", variant: "primary" },
    { id: "official", label: "Văn bản chính thức", variant: "official" },
    { id: "verified", label: "Trả lời có căn cứ", variant: "verified" },
  ];

  return (
    <div className="w-full" style={{ contain: "layout paint" }}>
      <motion.header
        initial={{ opacity: 0.9, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.28, ease: FM_EASE_OUT }}
        className="flex items-center justify-between min-h-[85px] md:min-h-[110px] rounded-[12px] px-3 py-2 md:px-5 md:py-3 mb-3 text-white border-b-[3px] border-[#00a65a] shadow-[0_4px_14px_rgba(0,104,55,0.22)]"
        style={{
          background: "linear-gradient(135deg, #005a30 0%, #00733c 100%)",
        }}
      >
        <div className="w-[54px] md:w-[72px] flex items-center justify-start shrink-0">
          <img
            src={logoUrl}
            alt="Logo VLUTE"
            width={66}
            height={66}
            className="w-[48px] h-[48px] md:w-[66px] md:h-[66px] object-contain shrink-0 block transition-transform duration-200 hover:scale-105"
            style={{ filter: "drop-shadow(0 2px 6px rgba(0, 0, 0, 0.3))" }}
          />
        </div>

        <div className="flex-1 min-w-0 text-center flex flex-col items-center justify-center px-2">
          <div className="flex items-center justify-center gap-2 md:gap-3 text-[0.95rem] md:text-[1.25rem] font-extrabold text-white tracking-[0.3px] leading-[1.3] text-center">
            <img
              src={avatarUrl}
              alt="Lucas Avatar"
              width={56}
              height={56}
              className="w-[40px] h-[40px] md:w-[56px] md:h-[56px] rounded-full object-cover shrink-0 shadow-[0_3px_8px_rgba(0,0,0,0.25)]"
            />
            <span className="break-words">{title}</span>
          </div>
          <p className="text-[0.75rem] md:text-[0.88rem] text-[#ecfdf5] mt-1 font-medium leading-[1.35]">
            {subtitle}
          </p>
        </div>

        <div className="hidden md:block md:w-[72px] shrink-0" aria-hidden="true" />
      </motion.header>

      <div className="flex flex-wrap items-center justify-center gap-2.5 mb-3.5 w-full">
        {badges.map((badge, idx) => {
          const cfg = BADGE_CONFIG[badge.id] || BADGE_CONFIG.search;
          const IconComp = cfg.Icon;
          return (
            <motion.div
              key={badge.id}
              initial={{ opacity: 0.85, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                duration: 0.26,
                delay: idx * 0.04,
                ease: FM_EASE_OUT,
              }}
              whileHover={{ y: -1, transition: { duration: 0.16 } }}
              className={`inline-flex items-center gap-1.5 text-white text-[0.82rem] font-semibold px-3.5 py-1.5 rounded-[8px] select-none transition-shadow duration-200 hover:shadow-[0_6px_14px_rgba(0,0,0,0.14)] ${cfg.className}`}
            >
              <IconComp className="w-4 h-4 shrink-0" strokeWidth={2} />
              <span>{badge.label}</span>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
