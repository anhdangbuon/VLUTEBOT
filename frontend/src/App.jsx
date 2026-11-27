import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, Menu, SendHorizontal } from "lucide-react";
import ChatMessage from "./components/ChatMessage.jsx";
import HeroHeader from "./components/HeroHeader.jsx";
import Sidebar from "./components/Sidebar.jsx";
import WelcomePrompts from "./components/WelcomePrompts.jsx";

const DEFAULT_WELCOME_CONTENT =
  "**Xin chào! Mình là Lucas** – trợ lý hỗ trợ tra cứu Quy chế Đào tạo & Quy định sinh viên VLUTE.\n\nBạn có thể chọn nhanh một trong các câu hỏi gợi ý bên dưới hoặc nhập trực tiếp thắc mắc về học bổng, miễn giảm học phí, công tác xã hội, kỷ luật hay học vụ!";

const DEFAULT_PLACEHOLDER =
  "Hỏi về quy chế đào tạo, học bổng, học phí, học vụ VLUTE...";

const FM_EASE_OUT = [0.22, 1, 0.36, 1];

function makeInitialMessages(welcomeContent = DEFAULT_WELCOME_CONTENT) {
  return [
    {
      id: "welcome-0",
      role: "assistant",
      content: welcomeContent,
      isWelcome: true,
      isRefusal: true,
      isGreeting: false,
      isDeptInquiry: false,
      verified: false,
      elapsedTime: null,
      contact: null,
      followups: [],
      sources: [],
    },
  ];
}

export default function App() {
  const [initData, setInitData] = useState(null);
  const [welcomePrompts, setWelcomePrompts] = useState([]);
  const [shuffleCount, setShuffleCount] = useState(0);
  const [isShuffling, setIsShuffling] = useState(false);

  const [messages, setMessages] = useState(() => makeInitialMessages());
  const [inputText, setInputText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [askedQueries, setAskedQueries] = useState([]);
  const [greetingTurnCount, setGreetingTurnCount] = useState(0);

  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(max-width: 767px)").matches : false
  );
  const [sidebarOpen, setSidebarOpen] = useState(() =>
    typeof window !== "undefined" ? !window.matchMedia("(max-width: 767px)").matches : true
  );
  const [sidebarWidth, setSidebarWidth] = useState(420);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [showScrollBottomBtn, setShowScrollBottomBtn] = useState(false);

  const scrollContainerRef = useRef(null);
  const userScrolledUpRef = useRef(false);
  const prevScrollTopRef = useRef(0);
  const scrollRafRef = useRef(null);
  const abortControllerRef = useRef(null);
  const textareaRef = useRef(null);

  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setIsResizingSidebar(true);
  }, []);

  useEffect(() => {
    if (!isResizingSidebar) return undefined;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMouseMove = (e) => {
      const nextWidth = Math.min(560, Math.max(300, Math.round(e.clientX)));
      setSidebarWidth(nextWidth);
    };

    const onMouseUp = () => {
      setIsResizingSidebar(false);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    window.addEventListener("blur", onMouseUp);
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("blur", onMouseUp);
    };
  }, [isResizingSidebar]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const onChange = (e) => {
      setIsMobile(e.matches);
      setSidebarOpen(!e.matches);
      if (e.matches) {
        setIsResizingSidebar(false);
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    let active = true;
    fetch("/api/init")
      .then((res) => res.json())
      .then((data) => {
        if (!active) return;
        setInitData(data);
        if (Array.isArray(data.prompts)) {
          setWelcomePrompts(data.prompts);
        }
        if (data.welcome_content) {
          setMessages((prev) =>
            prev.length === 1 && prev[0].isWelcome
              ? [{ ...prev[0], content: data.welcome_content }]
              : prev
          );
        }
      })
      .catch((err) => {
        console.error("Failed to fetch /api/init:", err);
      });
    return () => {
      active = false;
    };
  }, []);

  const scheduleAutoScroll = useCallback(() => {
    if (messages.length <= 1 || userScrolledUpRef.current) return;
    if (scrollRafRef.current) return;
    scrollRafRef.current = window.requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const el = scrollContainerRef.current;
      if (!el || userScrolledUpRef.current) return;
      el.scrollTop = el.scrollHeight;
      prevScrollTopRef.current = el.scrollTop;
    });
  }, [messages.length]);

  useEffect(() => {
    scheduleAutoScroll();
  }, [messages, scheduleAutoScroll]);

  const handleMainScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const currentTop = el.scrollTop;
    const distFromBottom = el.scrollHeight - currentTop - el.clientHeight;
    const delta = currentTop - prevScrollTopRef.current;
    prevScrollTopRef.current = currentTop;

    if (distFromBottom <= 36) {
      userScrolledUpRef.current = false;
      setShowScrollBottomBtn(false);
    } else if (delta < -2) {
      userScrolledUpRef.current = true;
      setShowScrollBottomBtn(true);
    }
  }, []);

  const scrollToBottom = useCallback(() => {
    userScrolledUpRef.current = false;
    setShowScrollBottomBtn(false);
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, []);

  const handleShufflePrompts = useCallback(async () => {
    if (isShuffling) return;
    setIsShuffling(true);
    try {
      const previousQueries = welcomePrompts.map((p) => p.query).filter(Boolean);
      const res = await fetch("/api/prompts/shuffle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ previous_queries: previousQueries }),
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.prompts) && data.prompts.length > 0) {
          setWelcomePrompts(data.prompts);
          setShuffleCount((c) => c + 1);
        }
      }
    } catch (err) {
      console.error("Failed to shuffle prompts:", err);
    } finally {
      setIsShuffling(false);
    }
  }, [isShuffling, welcomePrompts]);

  const handleResetChat = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    userScrolledUpRef.current = false;
    setShowScrollBottomBtn(false);
    setAskedQueries([]);
    setGreetingTurnCount(0);
    setMessages(makeInitialMessages(initData?.welcome_content || DEFAULT_WELCOME_CONTENT));

    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTop = 0;
    }

    try {
      const previousQueries = welcomePrompts.map((p) => p.query).filter(Boolean);
      const res = await fetch("/api/prompts/shuffle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ previous_queries: previousQueries }),
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.prompts) && data.prompts.length > 0) {
          setWelcomePrompts(data.prompts);
          setShuffleCount((c) => c + 1);
        }
      }
    } catch (err) {
      console.error("Failed to refresh welcome prompts on reset:", err);
    }
  }, [initData?.welcome_content, welcomePrompts]);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, []);

  const handleSendQuery = useCallback(
    async (rawQuery) => {
      const trimmed = (rawQuery ?? inputText).trim();
      if (!trimmed) return;

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }

      if (rawQuery === undefined) {
        setInputText("");
        if (textareaRef.current) {
          textareaRef.current.style.height = "auto";
        }
      }

      userScrolledUpRef.current = false;
      setShowScrollBottomBtn(false);
      setIsStreaming(true);

      const userMsgId = `user-${Date.now()}`;
      const botMsgId = `assistant-${Date.now() + 1}`;
      const finalizedMessages = messages.map((m) =>
        m.isThinking || m.isStreaming
          ? {
              ...m,
              content: m.content || "*(Đã hủy lượt trả lời trước)*",
              isThinking: false,
              isStreaming: false,
              verified: false,
              isRefusal: true,
              contact: null,
            }
          : m
      );
      const historyPayload = finalizedMessages
        .filter((m) => !m.isThinking && !m.isStreaming && m.content !== "*(Đã hủy lượt trả lời trước)*")
        .map((m) => ({
          role: m.role,
          content: m.content,
          query: m.query || "",
          is_welcome: Boolean(m.isWelcome),
          is_refusal: Boolean(m.isRefusal),
          is_greeting: Boolean(m.isGreeting),
          is_dept_inquiry: Boolean(m.isDeptInquiry),
        }));
      const nextAskedQueries = [...askedQueries, trimmed];
      setAskedQueries(nextAskedQueries);

      setMessages([
        ...finalizedMessages,
        { id: userMsgId, role: "user", content: trimmed },
        {
          id: botMsgId,
          role: "assistant",
          content: "",
          isThinking: true,
          isStreaming: true,
          isWelcome: false,
          verified: false,
          isRefusal: false,
          elapsedTime: null,
          contact: null,
          followups: [],
          sources: [],
          query: trimmed,
        },
      ]);

      const controller = new AbortController();
      abortControllerRef.current = controller;
      let nextGreetingCount = greetingTurnCount;
      let streamedText = "";

      try {
        const res = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: trimmed,
            messages: historyPayload,
            asked_queries: askedQueries,
            greeting_turn_count: greetingTurnCount,
          }),
          signal: controller.signal,
        });

        if (controller.signal.aborted || abortControllerRef.current !== controller) {
          return;
        }
        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          if (controller.signal.aborted || abortControllerRef.current !== controller) {
            try {
              await reader.cancel();
            } catch {
              // ignore cancel error
            }
            return;
          }
          const { value, done } = await reader.read();
          if (controller.signal.aborted || abortControllerRef.current !== controller) {
            return;
          }
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const frames = buffer.split("\n\n");
          buffer = frames.pop() || "";

          for (const frame of frames) {
            const lines = frame.split("\n");
            for (const line of lines) {
              if (!line.startsWith("data:")) continue;
              const rawJson = line.slice(5).trim();
              if (!rawJson) continue;
              let evt;
              try {
                evt = JSON.parse(rawJson);
              } catch {
                continue;
              }

              if (evt.type === "chunk" && typeof evt.content === "string") {
                streamedText += evt.content;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === botMsgId
                      ? { ...m, content: streamedText, isThinking: false, isStreaming: true }
                      : m
                  )
                );
              } else if (evt.type === "meta") {
                if (evt.is_greeting) {
                  nextGreetingCount += 1;
                }
                const metaRefusal = Boolean(evt.is_refusal);
                const metaVerified = metaRefusal ? false : Boolean(evt.verified);
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === botMsgId
                      ? {
                          ...m,
                          isThinking: false,
                          isStreaming: false,
                          verified: metaVerified,
                          elapsedTime: metaVerified ? (evt.elapsed_time ?? null) : null,
                          cacheHit: Boolean(evt.cache_hit),
                          contact: metaRefusal ? null : (evt.contact || null),
                          followups: Array.isArray(evt.followups) ? evt.followups : [],
                          sources: metaRefusal ? [] : (Array.isArray(evt.sources) ? evt.sources : []),
                          query: evt.rewritten_query || trimmed,
                          isRefusal: metaRefusal,
                          isGreeting: Boolean(evt.is_greeting),
                          isDeptInquiry: Boolean(evt.is_dept_inquiry),
                        }
                      : m
                  )
                );
              } else if (evt.type === "done") {
                setMessages((prev) =>
                  prev.map((m) => {
                    if (m.id !== botMsgId) return m;
                    const doneRefusal =
                      typeof evt.is_refusal === "boolean" ? evt.is_refusal : Boolean(m.isRefusal);
                    const doneVerified = doneRefusal
                      ? false
                      : typeof evt.verified === "boolean"
                        ? evt.verified
                        : Boolean(m.verified);
                    return {
                      ...m,
                      isThinking: false,
                      isStreaming: false,
                      isRefusal: doneRefusal,
                      verified: doneVerified,
                      contact: doneRefusal ? null : (evt.contact !== undefined ? evt.contact : m.contact),
                    };
                  })
                );
              }
            }
          }
        }

        if (nextGreetingCount !== greetingTurnCount) {
          setGreetingTurnCount(nextGreetingCount);
        }
      } catch (err) {
        if (err.name !== "AbortError" && abortControllerRef.current === controller) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === botMsgId
                ? {
                    ...m,
                    content:
                      streamedText ||
                      `⚠️ Kết nối tạm thời bị gián đoạn (${err.message}). Bạn vui lòng thử gửi lại câu hỏi nhé!`,
                    isThinking: false,
                    isStreaming: false,
                    verified: false,
                    contact: null,
                    isRefusal: true,
                  }
                : m
            )
          );
        }
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          setIsStreaming(false);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === botMsgId ? { ...m, isThinking: false, isStreaming: false } : m
            )
          );
        }
      }
    },
    [askedQueries, greetingTurnCount, inputText, messages]
  );

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendQuery();
    }
  };

  const handleTextareaChange = (e) => {
    setInputText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
    el.style.overflowY = el.scrollHeight > 140 ? "auto" : "hidden";
  };

  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === "assistant") return messages[i].id;
    }
    return null;
  }, [messages]);

  const showWelcomePrompts = messages.length <= 1 && !isStreaming;
  const placeholder = initData?.input_placeholder || DEFAULT_PLACEHOLDER;
  const avatarUrl = initData?.branding?.avatar_url || "/assets/lucas_avatar.png";

  return (
    <div
      data-testid="app-root"
      className={`flex h-screen w-full overflow-hidden vlute-page-bg text-[#1e293b] ${
        isResizingSidebar ? "select-none" : ""
      }`}
    >
      <Sidebar
        isOpen={sidebarOpen}
        isMobile={isMobile}
        width={sidebarWidth}
        isResizing={isResizingSidebar}
        onResizeStart={handleResizeStart}
        onToggle={() => setSidebarOpen((v) => !v)}
        onClose={() => setSidebarOpen(false)}
        onResetChat={handleResetChat}
        branding={initData?.branding}
        sidebarLinks={initData?.sidebar_links}
        departments={initData?.departments}
      />

      <div
        style={{ paddingLeft: !isMobile && sidebarOpen ? sidebarWidth : 0 }}
        className={`relative flex-1 flex flex-col min-w-0 h-full ${
          isResizingSidebar
            ? "pointer-events-none"
            : "transition-[padding] duration-[340ms] ease-[cubic-bezier(0.22,1,0.36,1)]"
        }`}
      >
        {/* Persistent expand sidebar button when collapsed (desktop) or always on mobile */}
        <AnimatePresence>
          {(!sidebarOpen || isMobile) && (
            <motion.button
              key="expand-sidebar-btn"
              type="button"
              data-testid="sidebar-expand-btn"
              aria-label="Mở bảng điều khiển"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ duration: 0.18, ease: FM_EASE_OUT }}
              onClick={() => setSidebarOpen(true)}
              style={{ touchAction: "manipulation" }}
              className="fixed top-3 left-3.5 z-30 w-[38px] h-[38px] rounded-[8px] bg-[#141a1d]/95 hover:bg-[#00703c] border border-[#00a65a]/60 text-white shadow-md flex items-center justify-center transition-colors duration-150 cursor-pointer"
            >
              <Menu className="w-4 h-4 text-white" strokeWidth={2.4} />
            </motion.button>
          )}
        </AnimatePresence>

        {/* Scrollable main chat viewport */}
        <main
          ref={scrollContainerRef}
          onScroll={handleMainScroll}
          className={`flex-1 overflow-y-auto main-scroll px-3 sm:px-5 pt-14 md:pt-7 pb-6 ${
            !sidebarOpen && !isMobile ? "md:pl-16" : ""
          }`}
        >
          <div className="max-w-[820px] mx-auto w-full">
            <HeroHeader branding={initData?.branding} />

            <div className="mt-2">
              {messages.map((msg) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  avatarUrl={avatarUrl}
                  isLatestAssistant={msg.id === lastAssistantId}
                  onSelectFollowup={(q) => handleSendQuery(q)}
                  isGlobalStreaming={isStreaming}
                />
              ))}
            </div>

            {showWelcomePrompts && (
              <WelcomePrompts
                prompts={welcomePrompts}
                shuffleCount={shuffleCount}
                isShuffling={isShuffling}
                onShuffle={handleShufflePrompts}
                onSelectPrompt={(q) => handleSendQuery(q)}
              />
            )}

            <div className="h-4" aria-hidden="true" />
          </div>
        </main>

        {/* Floating scroll-to-bottom button when user scrolled up during conversation */}
        <AnimatePresence>
          {showScrollBottomBtn && messages.length > 1 && (
            <motion.button
              key="scroll-to-bottom-btn"
              type="button"
              data-testid="scroll-to-bottom-btn"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              transition={{ duration: 0.18, ease: FM_EASE_OUT }}
              onClick={scrollToBottom}
              className="absolute right-5 bottom-[84px] z-20 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/95 border border-[#00703c] text-[#00703c] text-[0.78rem] font-semibold shadow-md hover:bg-[#00703c] hover:text-white transition-colors duration-150 cursor-pointer"
            >
              <ArrowDown className="w-3.5 h-3.5" strokeWidth={2.4} />
              <span>Xuống cuối</span>
            </motion.button>
          )}
        </AnimatePresence>

        {/* Bottom sticky chat input */}
        <div
          className="shrink-0 w-full px-3 sm:px-5 pt-3 pb-4"
          style={{
            background:
              "linear-gradient(to bottom, rgba(246, 249, 248, 0) 0%, rgba(246, 249, 248, 0.92) 32%, #f6f9f8 100%)",
          }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendQuery();
            }}
            className="max-w-[820px] mx-auto w-full flex items-end gap-2 bg-white border-[1.5px] border-[#cbd5e1] rounded-[12px] px-3.5 py-2 shadow-sm transition-all duration-200 focus-within:border-[#00703c] focus-within:shadow-[0_0_0_3px_rgba(0,112,60,0.15),0_6px_18px_rgba(0,112,60,0.10)]"
          >
            <textarea
              ref={textareaRef}
              rows={1}
              data-testid="chat-input"
              value={inputText}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className="flex-1 resize-none overflow-hidden bg-transparent border-0 outline-none text-[0.86rem] md:text-[0.95rem] leading-[1.45] text-[#1e293b] placeholder:text-slate-400 py-1 max-h-[140px]"
            />
            <motion.button
              type="submit"
              data-testid="send-btn"
              aria-label="Gửi câu hỏi"
              disabled={!inputText.trim()}
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.95 }}
              className="shrink-0 w-9 h-9 rounded-[10px] bg-[#00703c] hover:bg-[#005a30] disabled:bg-slate-300 text-white flex items-center justify-center transition-colors duration-150 cursor-pointer disabled:cursor-not-allowed"
            >
              <SendHorizontal className="w-4 h-4" strokeWidth={2.2} />
            </motion.button>
          </form>
        </div>
      </div>
    </div>
  );
}
