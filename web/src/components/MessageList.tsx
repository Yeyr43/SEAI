import React, { useEffect, useRef } from 'react'
import { marked } from 'marked'
import type { Message } from '../types'

marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch {
    return text.replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  const isSystem = msg.role === 'system'

  if (isSystem) {
    return (
      <div className="message system-msg">
        <span className="system-badge">系统</span>
        <span>{msg.content}</span>
      </div>
    )
  }

  return (
    <div className={`message ${isUser ? 'user-msg' : 'assistant-msg'}`}>
      <div className="msg-avatar">
        {isUser ? '👤' : '🤖'}
      </div>
      <div className="msg-body">
        <div
          className="msg-content"
          dangerouslySetInnerHTML={{
            __html: isUser ? msg.content.replace(/</g, '&lt;') : renderMarkdown(msg.content),
          }}
        />
        {msg.tool_calls && msg.tool_calls.length > 0 && (
          <div className="tool-calls">
            {msg.tool_calls.map((tc) => (
              <details key={tc.id} className="tool-call">
                <summary>🔧 {tc.name}</summary>
                <pre>{JSON.stringify(tc.arguments, null, 2)}</pre>
                {tc.result && (
                  <div className="tool-result">
                    <strong>结果:</strong>
                    <pre>{tc.result.slice(0, 2000)}</pre>
                  </div>
                )}
              </details>
            ))}
          </div>
        )}
        <span className="msg-time">{new Date(msg.timestamp).toLocaleTimeString()}</span>
      </div>
    </div>
  )
}

export const MessageList: React.FC = () => {
  const { messages, streaming } = useChatStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="message-list">
      {messages.length === 0 && (
        <div className="empty-chat">
          <img src="/ui/seai.png" alt="SEAI" style={{ width: 64, height: 64, opacity: 0.3 }} />
          <h2>SEAI 智能助手</h2>
          <p>开始一段新的对话吧</p>
        </div>
      )}
      {messages.map((msg) => (
        <MessageBubble key={msg.id} msg={msg} />
      ))}
      {streaming && <div className="typing-indicator"><span /><span /><span /></div>}
      <div ref={bottomRef} />
    </div>
  )
}

import { useChatStore } from '../stores/chatStore'
