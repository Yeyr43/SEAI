import React from 'react'
import { useChatStore } from '../stores/chatStore'

const icon = (name: string, cls = '') => (
  <img src={`/ui/${name}.png`} className={`icon ${cls}`} alt={name} />
)

export const TopBar: React.FC = () => {
  const { theme, toggleTheme } = useChatStore()

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="plain-btn" title="SEAI">
          <img src="/ui/seai.png" alt="SEAI" style={{ width: 28, height: 28 }} />
        </button>
      </div>
      <div className="topbar-spacer" />
      <div className="topbar-right">
        <button className="icon-btn" onClick={toggleTheme} title="切换主题">
          {icon(theme === 'dark' ? 'light' : 'dark', '')}
        </button>
        <div className="win-ctrl">
          <button className="win-ctrl-btn" id="btn-minimize" title="最小化">
            <img src="/ui/minimize.svg" alt="min" />
          </button>
          <button className="win-ctrl-btn" id="btn-maximize" title="最大化">
            <img src="/ui/maximize.svg" alt="max" />
          </button>
          <button className="win-ctrl-btn close-btn" id="btn-close" title="关闭">
            <img src="/ui/close.svg" alt="close" />
          </button>
        </div>
      </div>
    </header>
  )
}
