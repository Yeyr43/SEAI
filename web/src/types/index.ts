export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool_calls?: ToolCall[]
  timestamp: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  result?: string
}

export interface ChatRequest {
  session_id: string
  message: string
  model?: string
  system_prompt?: string
}

export interface SSEEvent {
  type: 'token' | 'tool_start' | 'tool_end' | 'done' | 'error' | 'title'
  data: string
}

export interface AppConfig {
  models: string[]
  tools: string[]
  web_search_enabled: boolean
  max_context_tokens: number
}

export type Theme = 'dark' | 'light'
