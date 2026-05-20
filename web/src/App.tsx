import { useEffect } from 'react'
import { TopBar } from './components/TopBar'
import { SessionPanel } from './components/SessionPanel'
import { MessageList } from './components/MessageList'
import { InputArea } from './components/InputArea'
import { useChatStore } from './stores/chatStore'
import { api } from './api/client'
import './App.css'

const App: React.FC = () => {
  const { setSessions, setCurrentSession, setMessages, theme } = useChatStore()

  useEffect(() => {
    document.body.className = theme
    api.getSessions()
      .then((sessions) => {
        setSessions(sessions)
        if (sessions.length > 0) {
          setCurrentSession(sessions[0].id)
          api.getMessages(sessions[0].id).then(setMessages).catch(console.error)
        }
      })
      .catch(console.error)
  }, [])

  return (
    <>
      <TopBar />
      <div className="app">
        <SessionPanel />
        <main className="chat-area">
          <MessageList />
          <InputArea />
        </main>
      </div>
    </>
  )
}

export default App
