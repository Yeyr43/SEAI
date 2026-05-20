import { create } from 'zustand'
import type { Message, Session } from '../types'

interface ChatState {
  sessions: Session[]
  currentSessionId: string | null
  messages: Message[]
  streaming: boolean
  abortController: AbortController | null
  searchQuery: string
  theme: 'dark' | 'light'

  setSessions: (sessions: Session[]) => void
  setCurrentSession: (id: string) => void
  addSession: (session: Session) => void
  removeSession: (id: string) => void
  setMessages: (messages: Message[]) => void
  addMessage: (msg: Message) => void
  appendToLastMessage: (chunk: string) => void
  setStreaming: (v: boolean) => void
  setAbortController: (c: AbortController | null) => void
  setSearchQuery: (q: string) => void
  toggleTheme: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  currentSessionId: null,
  messages: [],
  streaming: false,
  abortController: null,
  searchQuery: '',
  theme: (localStorage.getItem('seai-theme') as 'dark' | 'light') || 'dark',

  setSessions: (sessions) => set({ sessions }),
  setCurrentSession: (id) => set({ currentSessionId: id, messages: [] }),
  addSession: (session) => set((s) => ({ sessions: [session, ...s.sessions] })),
  removeSession: (id) => set((s) => ({
    sessions: s.sessions.filter((ses) => ses.id !== id),
    currentSessionId: s.currentSessionId === id ? null : s.currentSessionId,
  })),
  setMessages: (messages) => set({ messages }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  appendToLastMessage: (chunk) => set((s) => {
    const msgs = [...s.messages]
    if (msgs.length > 0 && msgs[msgs.length - 1].role === 'assistant') {
      msgs[msgs.length - 1] = {
        ...msgs[msgs.length - 1],
        content: msgs[msgs.length - 1].content + chunk,
      }
    }
    return { messages: msgs }
  }),
  setStreaming: (streaming) => set({ streaming }),
  setAbortController: (c) => set({ abortController: c }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  toggleTheme: () => set((s) => {
    const next = s.theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem('seai-theme', next)
    document.body.className = next
    return { theme: next }
  }),
}))
