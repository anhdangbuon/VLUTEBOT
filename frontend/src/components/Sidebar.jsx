import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ClipboardList,
  Compass,
  CreditCard,
  FileEdit,
  Globe,
  Landmark,
  Link2,
  Mail,
  MapPin,
  Menu,
  Monitor,
  Phone,
  RotateCcw,
  Users,
  Wallet,
} from "lucide-react";

const FM_EASE_OUT = [0.22, 1, 0.36, 1];
const FM_SPRING = { type: "spring", stiffness: 360, damping: 32 };

const ICON_MAP = {
  globe: Globe,
  "file-edit": FileEdit,
  monitor: Monitor,
  "credit-card": CreditCard,
  compass: Compass,
  "clipboard-list": ClipboardList,
  users: Users,
  wallet: Wallet,
  link: Link2,
  landmark: Landmark,
};

const DEFAULT_SIDEBAR_LINK_GROUPS = [
  {
    title: "HỆ THỐNG HỌC TẬP",
    icon: "link",
    items: [
      {
        label: "My VLUTE",
        title: "Cổng thông tin My VLUTE",
        url: "https://vlute.edu.vn/",
        icon: "globe",
      },
      {
        label: "ĐK Học phần",
        title: "Đăng ký học phần",
        url: "https://daotao.vlute.edu.vn/sinh-vien",
        icon: "file-edit",
      },
      {
        label: "E-Learning",
        title: "Học trực tuyến E-Learning",
        url: "http://elearning.vlute.edu.vn/",
        icon: "monitor",
      },
      {
        label: "Thanh toán",
        title: "Cổng thanh toán Trực tuyến",
        url: "https://thanhtoan.vlute.edu.vn/",
        icon: "credit-card",
      },
    ],
  },
  {
    title: "ĐƠN VỊ HỖ TRỢ",
    icon: "landmark",
    items: [
      {
        label: "Tuyển sinh",
        title: "Phòng Tuyển sinh",
        url: "https://tuyensinh.vlute.edu.vn/",
        icon: "compass",
      },
      {
        label: "Đào tạo (A1.101)",
        title: "Phòng Đào tạo (A1.101)",
        url: "http://pdt.vlute.edu.vn/",
        icon: "clipboard-list",
      },
      {
        label: "CTSV (A1.102)",
        title: "Phòng Công tác SV (A1.102)",
        url: "http://cgtdt-dsa.vlute.edu.vn/",
        icon: "users",
      },
      {
        label: "KHTC (Tầng trệt)",
        title: "Phòng Kế hoạch - Tài chính",
        url: "https://vlute.edu.vn",
        icon: "wallet",
      },
    ],
  },
];

function SidebarContent({
  onToggle,
  onResetChat,
  branding,
  sidebarLinks,
  departments,
}) {
  const logoUrl = branding?.logo_url || "/assets/logo_vlute.png";
  const uniLine1 = branding?.university_line_1 || "TRƯỜNG ĐẠI HỌC";
  const uniLine2 = branding?.university_line_2 || "CNKT VĨNH LONG";
  const uniUnit = branding?.university_unit || "QUẢN LÝ ĐÀO TẠO & HỌC VỤ";
  const address =
    branding?.address || "Số 73 Nguyễn Huệ, Phường Long Châu, Tỉnh Vĩnh Long";
  const copyrightTitle =
    branding?.copyright_title || "© Trường ĐH Công nghệ Kỹ thuật Vĩnh Long";
  const copyrightSub =
    branding?.copyright_sub || "(Tiền thân: Trường ĐH Sư phạm Kỹ thuật Vĩnh Long)";
  const resolvedLinkGroups =
    Array.isArray(sidebarLinks) && sidebarLinks.length > 0
      ? sidebarLinks
      : DEFAULT_SIDEBAR_LINK_GROUPS;

  return (
    <div className="flex flex-col h-full w-full bg-[#222d32] text-[#b8c7ce] border-r border-[#1a2226] shadow-[4px_0_24px_rgba(0,0,0,0.3)] select-none">
      {/* Header badge & collapse button */}
      <div className="px-3.5 pt-3 pb-1 shrink-0">
        <div className="flex items-center justify-between gap-2 bg-[#141a1d] border border-[#2b3b42] rounded-[8px] min-h-[46px] px-4 py-2">
          <div className="text-[#b8c7ce] text-[0.73rem] font-bold tracking-[0.3px] uppercase whitespace-nowrap truncate">
            BẢNG ĐIỀU KHIỂN HỌC VỤ
          </div>
          <button
            type="button"
            data-testid="sidebar-collapse-btn"
            aria-label="Thu gọn bảng điều khiển"
            onClick={onToggle}
            className="w-[30px] h-[30px] rounded-[6px] border border-white/15 bg-white/10 hover:bg-[#00a65a]/25 hover:border-[#00a65a] text-white flex items-center justify-center transition-colors duration-150 shrink-0 cursor-pointer"
          >
            <Menu className="w-4 h-4 text-white" strokeWidth={2.4} />
          </button>
        </div>
      </div>

      {/* Scrollable sidebar interior */}
      <div className="flex-1 overflow-y-auto sidebar-scroll px-3.5 pb-5">
        <div className="flex justify-center items-center w-full pt-3.5 pb-2">
          <img
            src={logoUrl}
            alt="Logo VLUTE"
            width={95}
            height={95}
            className="w-[95px] h-[95px] object-contain block"
            style={{ filter: "drop-shadow(0 3px 8px rgba(0,0,0,0.4))" }}
          />
        </div>

        <div className="text-center text-[#b8c7ce] font-extrabold text-[0.92rem] tracking-[0.3px] mb-1 leading-[1.35]">
          {uniLine1}
          <br />
          <span className="whitespace-nowrap text-[#b8c7ce]">{uniLine2}</span>
        </div>

        <div className="text-center text-[#b8c7ce] font-bold text-[0.76rem] tracking-[0.6px] uppercase mb-2.5">
          {uniUnit}
        </div>

        <div
          data-testid="sidebar-address-box"
          className="flex items-center justify-center gap-1.5 text-center text-[#cbd5e1] text-[0.69rem] px-2 py-1.5 bg-[rgba(0,0,0,0.3)] border border-white/10 rounded-[8px] leading-[1.4] whitespace-nowrap overflow-hidden"
        >
          <MapPin className="w-3.5 h-3.5 text-[#00a65a] shrink-0" strokeWidth={2} />
          <span className="truncate">{address}</span>
        </div>

        <motion.button
          type="button"
          data-testid="reset-chat-btn"
          onClick={onResetChat}
          whileHover={{ y: -2, transition: { duration: 0.16, ease: FM_EASE_OUT } }}
          whileTap={{ scale: 0.97, transition: { duration: 0.12 } }}
          className="w-full mt-2.5 flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-[#00a65a] hover:bg-[#008d4c] text-white font-bold text-[0.88rem] shadow-sm hover:shadow-[0_6px_16px_rgba(0,166,90,0.28)] transition-colors duration-200 cursor-pointer"
        >
          <RotateCcw className="w-[15px] h-[15px] text-white shrink-0" strokeWidth={2.2} />
          <span>Làm mới cuộc trò chuyện</span>
        </motion.button>

        {/* Link cards: HỆ THỐNG HỌC TẬP + ĐƠN VỊ HỖ TRỢ */}
        <div
          data-testid="sidebar-links-card"
          className="bg-[#1e282c] border border-[#374850] rounded-[8px] p-3 mt-2.5"
        >
          {resolvedLinkGroups.map((group, gIdx) => {
            const GroupIcon = ICON_MAP[group.icon] || Link2;
            return (
              <div
                key={group.title}
                data-testid="sidebar-link-group"
                className={gIdx > 0 ? "mt-3" : ""}
              >
                <div className="text-[0.78rem] font-bold text-[#b8c7ce] tracking-[0.5px] uppercase mb-2 flex items-center gap-1.5">
                  <GroupIcon className="w-3.5 h-3.5 text-[#00a65a] shrink-0" strokeWidth={2} />
                  <span>{group.title}</span>
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  {(group.items || []).map((item) => {
                    const ItemIcon = ICON_MAP[item.icon] || Globe;
                    return (
                      <a
                        key={item.label}
                        data-testid="sidebar-link-item"
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={item.title}
                        className="group flex items-center gap-1.5 px-2 py-1.5 rounded-[6px] bg-[#141b1e] border border-[#2b3b42] text-[#cbd5e1] text-[0.74rem] font-medium hover:bg-[#00a65a] hover:border-[#00a65a] hover:text-white hover:-translate-y-0.5 hover:shadow-[0_4px_12px_rgba(0,166,90,0.24)] active:translate-y-0 active:scale-[0.97] transition-all duration-150 overflow-hidden whitespace-nowrap"
                      >
                        <ItemIcon
                          className="w-3.5 h-3.5 text-[#00a65a] group-hover:text-white group-hover:translate-x-0.5 transition-all duration-150 shrink-0"
                          strokeWidth={2}
                        />
                        <span className="truncate">{item.label}</span>
                      </a>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Dynamic department contacts */}
        <div
          data-testid="sidebar-contact-card"
          className="bg-[#1e282c] border border-[#374850] hover:border-[#00a65a] rounded-[8px] p-3 mt-2.5 transition-colors duration-200"
        >
          <div className="font-bold text-white mb-2 text-[0.84rem] flex items-center gap-1.5">
            <Phone className="w-3.5 h-3.5 text-[#00a65a] shrink-0" strokeWidth={2} />
            <span>ĐẦU MỐI LIÊN HỆ PHÒNG BAN:</span>
          </div>
          <div className="space-y-2">
            {(departments || []).map((dept) => (
              <div key={dept.key} className="text-[0.8rem] leading-[1.45]">
                <div className="font-bold text-white">
                  • {dept.short_name}
                  {dept.location ? ` (${dept.location})` : ""}:
                </div>
                <div
                  data-testid="sidebar-dept-contact-row"
                  className="flex items-center gap-1.5 whitespace-nowrap mt-0.5 overflow-hidden"
                >
                  <Phone className="w-3 h-3 text-[#94a3b8] shrink-0" strokeWidth={2} />
                  <code className="bg-[#141b1e] text-[#b8c7ce] border border-[#2b3b42] px-1.5 py-0.5 rounded-[4px] text-[0.72rem] shrink-0">
                    {dept.phone}
                  </code>
                  <span className="text-[#475569] shrink-0">|</span>
                  <Mail className="w-3 h-3 text-[#94a3b8] shrink-0" strokeWidth={2} />
                  <span className="italic text-[#b8c7ce] text-[0.72rem] truncate">
                    {dept.email}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Copyright */}
        <div className="mt-2.5 p-3 bg-black/20 border border-white/5 rounded-[8px] text-[0.72rem] text-[#94a3b8] text-center leading-[1.45]">
          <div className="text-[#cbd5e1] font-bold">{copyrightTitle}</div>
          <div className="text-[0.68rem] text-[#b8c7ce] mt-0.5">{copyrightSub}</div>
        </div>
      </div>
    </div>
  );
}

export default function Sidebar({
  isOpen,
  isMobile,
  width = 360,
  onResizeStart,
  onToggle,
  onClose,
  onResetChat,
  branding,
  sidebarLinks,
  departments,
}) {
  if (isMobile) {
    return (
      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              key="sidebar-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={onClose}
              className="fixed inset-0 z-40 bg-slate-900/55 backdrop-blur-[1px]"
              aria-hidden="true"
            />
            <motion.aside
              key="sidebar-mobile-drawer"
              data-testid="vlute-sidebar"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={FM_SPRING}
              className="fixed inset-y-0 left-0 z-50 w-[85vw] max-w-[340px] h-full"
            >
              <SidebarContent
                onToggle={onClose}
                onResetChat={() => {
                  onResetChat();
                  onClose();
                }}
                branding={branding}
                sidebarLinks={sidebarLinks}
                departments={departments}
              />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    );
  }

  return (
    <AnimatePresence initial={false}>
      {isOpen && (
        <motion.aside
          key="sidebar-desktop"
          data-testid="vlute-sidebar"
          style={{ width }}
          initial={{ x: -width }}
          animate={{ x: 0 }}
          exit={{ x: -width }}
          transition={{ duration: 0.34, ease: FM_EASE_OUT }}
          className="fixed inset-y-0 left-0 z-30 h-full"
        >
          <SidebarContent
            onToggle={onToggle}
            onResetChat={onResetChat}
            branding={branding}
            sidebarLinks={sidebarLinks}
            departments={departments}
          />
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Kéo để thay đổi độ rộng bảng điều khiển"
            data-testid="sidebar-resize-handle"
            onMouseDown={onResizeStart}
            className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize hover:bg-[#00a65a]/70 active:bg-[#00a65a] transition-colors z-40"
          />
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
