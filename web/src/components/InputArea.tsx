import React, { useState, useRef, useCallback } from 'react'
import { useChatStore } from '../stores/chatStore'
import { createChatStream } from '../api/client'
import type { Message } from '../types'

export const InputArea: React.FC = () => {
  const [input, setInput] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const {
    currentSessionId, streaming, setStreaming,
    addMessage, appendToLastMessage, setAbortController,
    abortController,
  } = useChatStore()

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || !currentSessionId || streaming) return

    setInput('')
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    addMessage(userMsg)

    const assistantId = crypto.randomUUID()
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    }
    addMessage(assistantMsg)
    setStreaming(true)

    const controller = new AbortController()
    setAbortController(controller)

    createChatStream(
      { session_id: currentSessionId, message: text },
      (chunk) => appendToLastMessage(chunk),
      (name) => console.log('tool start:', name),
      (name, result) => {
        const msgs = useChatStore.getState().messages
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant') {
          last.tool_calls = [
            ...(last.tool_calls || []),
            { id: crypto.randomUUID(), name, arguments: {}, result },
          ]
        }
      },
      (_fullText) => {
        setStreaming(false)
        setAbortController(null)
      },
      (err) => {
        setStreaming(false)
        setAbortController(null)
        addMessage({
          id: crypto.randomUUID(),
          role: 'system',
          content: `错误: ${err}`,
          timestamp: new Date().toISOString(),
        })
      },
      (title) => console.log('title:', title),
      controller.signal,
    )
  }, [input, currentSessionId, streaming])

  const stop = useCallback(() => {
    abortController?.abort()
    setStreaming(false)
    setAbortController(null)
  }, [abortController])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="input-area">
      <div className="input-row">
        <button
          className={`icon-btn toggle-btn ${webSearch ? 'active' : ''}`}
          onClick={() => setWebSearch(!webSearch)}
          title="联网搜索"
        >
          <img src="/ui/net.png" alt="net" style={{ width: 20, height: 20 }} />
        </button>
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          rows={1}
          disabled={streaming}
        />
        {streaming ? (
          <button className="icon-btn stop-btn" onClick={stop} title="停止生成">
            <img src="/ui/stop.svg" alt="stop" style={{ width: 20, height: 20 }} />
          </button>
        ) : (
          <button className="icon-btn send-btn" onClick={send} title="发送">
            <img src="/ui/send.png" alt="send" style={{ width: 20, height: 20 }} />
          </button>
        )}
      </div>
    </div>
  )
}
