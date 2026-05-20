import React from 'react'
import { useChatStore } from '../stores/chatStore'
import { api } from '../api/client'

export const SessionPanel: React.FC = () => {
  const {
    sessions, currentSessionId, setCurrentSession,
    addSession, removeSession, searchQuery, setSearchQuery,
  } = useChatStore()

  const filtered = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleNewSession = async () => {
    try {
      const session = await api.createSession()
      addSession(session)
      setCurrentSession(session.id)
    } catch (e) {
      console.error('Failed to create session:', e)
    }
  }

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    try {
      await api.deleteSession(id)
      removeSession(id)
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }

  return (
    <aside className="session-panel">
      <input
        className="session-search"
        type="text"
        placeholder="搜索会话..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
      />
      <div className="session-list-container">
        {filtered.map((s) => (
          <div
            key={s.id}
            className={`session-item ${s.id === currentSessionId ? 'active' : ''}`}
            onClick={() => setCurrentSession(s.id)}
          >
            <div className="session-info">
              <span className="session-name">{s.title || '新会话'}</span>
              <span className="session-time">{new Date(s.updated_at).toLocaleDateString()}</span>
            </div>
            <div className="session-actions-wrap">
              <button
                className="plain-btn"
                onClick={(e) => handleDelete(e, s.id)}
                title="删除会话"
              >
                <img src="/ui/delete.png" alt="del" style={{ width: 16, height: 16 }} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <button className="new-session-btn" onClick={handleNewSession}>
        <img src="/ui/new.png" alt="+" style={{ width: 16, height: 16 }} />
        新建会话
      </button>
    </aside>
  )
}
