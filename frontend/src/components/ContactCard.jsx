import React from "react";
import { motion } from "framer-motion";
import { Phone } from "lucide-react";

const FM_EASE_OUT = [0.22, 1, 0.36, 1];

export default function ContactCard({ contact, disableAnimation = false }) {
  if (!contact) return null;

  const Wrapper = disableAnimation ? "div" : motion.div;
  const motionProps = disableAnimation
    ? {}
    : {
        initial: { opacity: 0.15, y: 8 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.34, ease: FM_EASE_OUT },
      };

  return (
    <Wrapper
      {...motionProps}
      data-testid="contact-footer-card"
      className="mt-3 px-4 py-3 bg-[#f8fafc] rounded-[8px] border-l-[3.5px] border-l-[#ff9800] text-[#334155] text-[0.9rem] transition-all duration-200 hover:bg-[#f1f5f9] hover:shadow-[0_6px_16px_rgba(0,90,48,0.12)]"
    >
      <div className="flex items-start gap-2 font-bold text-[#005a30]">
        <Phone className="w-[15px] h-[15px] mt-[3px] shrink-0 text-[#005a30]" strokeWidth={2.2} />
        <span>
          {contact.title}
          {contact.type === "pipeline" ? ":" : ":"}
        </span>
      </div>

      {contact.type === "pipeline" && Array.isArray(contact.steps) ? (
        <ul className="mt-1.5 mb-0 pl-5 space-y-1 text-[#334155] list-disc">
          {contact.steps.map((step) => (
            <li key={step.order} className="leading-[1.55]">
              <b>
                {step.order}. {step.name} ({step.role}):
              </b>{" "}
              {step.location} | ĐT: {step.phone} | Email: {step.email}
            </li>
          ))}
        </ul>
      ) : (
        <ul className="mt-1.5 mb-0 pl-5 space-y-1 text-[#334155] list-disc">
          <li className="leading-[1.55]">Vị trí: {contact.location}</li>
          <li className="leading-[1.55]">
            Điện thoại: {contact.phone} | Email: {contact.email}
          </li>
        </ul>
      )}
    </Wrapper>
  );
}
