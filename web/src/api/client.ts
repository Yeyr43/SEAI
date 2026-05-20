import type { Session, Message, ChatRequest, AppConfig } from '../types'

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  getConfig: () => request<AppConfig>('/config'),

  getSessions: () => request<Session[]>('/sessions'),

  getSession: (id: string) => request<Session>(`/sessions/${id}`),

  getMessages: (id: string) => request<Message[]>(`/sessions/${id}/messages`),

  createSession: (title?: string) =>
    request<Session>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),

  deleteSession: (id: string) =>
    request<void>(`/sessions/${id}`, { method: 'DELETE' }),

  switchSession: (id: string) =>
    request<{ messages: Message[] }>(`/sessions/${id}/switch`, { method: 'POST' }),

  sendMessage: (_body: ChatRequest): AbortController => {
    return new AbortController()
  },

  stopGeneration: () => request<void>('/chat/stop', { method: 'POST' }),
}

export function createChatStream(
  body: ChatRequest,
  onToken: (text: string) => void,
  onToolStart: (name: string) => void,
  onToolEnd: (name: string, result: string) => void,
  onDone: (fullText: string) => void,
  onError: (err: string) => void,
  onTitle: (title: string) => void,
  signal?: AbortSignal,
): () => void {
  let cancelled = false
  const url = `${BASE}/chat/stream`

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}: ${res.statusText}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) { onError('No response body'); return }

      const decoder = new TextDecoder()
      let buffer = ''
      let fullText = ''

      while (!cancelled) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (!data) continue

          try {
            const event = JSON.parse(data)
            switch (event.type) {
              case 'token':
                fullText += event.data
                onToken(event.data)
                break
              case 'tool_start':
                onToolStart(event.data)
                break
              case 'tool_end':
                onToolEnd(event.data.name || '', event.data.result || '')
                break
              case 'done':
                onDone(fullText)
                break
              case 'error':
                onError(event.data)
                break
              case 'title':
                onTitle(event.data)
                break
            }
          } catch {
            // skip unparseable events
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError(err.message)
    })

  return () => { cancelled = true }
}
