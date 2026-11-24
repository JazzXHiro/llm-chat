import { useEffect, useRef, useState } from 'react'
import { checkHealth, sendChat } from './api.js'
import ChatMessage from './components/ChatMessage.jsx'
import Composer from './components/Composer.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'

// A new random id = a new session on the backend (unknown id starts a new session)
function newSessionId() {
  if (window.crypto?.randomUUID) return `s-${crypto.randomUUID()}`
  // randomUUID needs HTTPS or localhost; this fallback covers plain-HTTP hosts
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export default function App() {
  // Passing the function (not calling it) runs it once per page load -> new session per load
  const [sessionId, setSessionId] = useState(newSessionId)
  // Each item: { role: 'user' | 'assistant' | 'error', content, metadata?, status? }
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [simulate, setSimulate] = useState('')
  const [sending, setSending] = useState(false)
  const [health, setHealth] = useState('checking') // 'checking' | null (offline) | health object
  const bottomRef = useRef(null)

  // The prompt is saved with the first successful turn, so lock it after that
  const promptLocked = messages.some((message) => message.role === 'assistant')

  useEffect(() => {
    checkHealth().then(setHealth)
  }, [])

  // Keep the newest message in view
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  function addMessage(message) {
    setMessages((previous) => [...previous, message])
  }

  async function handleSend() {
    if (sending) return
    const text = input
    setInput('') // contract: chat-input is empty after sending
    addMessage({ role: 'user', content: text })
    setSending(true)

    try {
      const data = await sendChat({ sessionId, message: text, systemPrompt, simulate })
      addMessage({ role: 'assistant', content: data.reply, metadata: data.metadata })
    } catch (error) {
      // 422 / 503 / network problems become a readable bubble, never a blank screen
      addMessage({ role: 'error', content: error.message, status: error.status })
    } finally {
      setSending(false)
    }
  }

  function handleNewChat() {
    setSessionId(newSessionId())
    setMessages([])
    setInput('')
  }

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Lyftr Chat</h1>
          <p className="session-id" title="A new session starts on every page load">
            Session <code>{sessionId}</code>
          </p>
        </div>
        <div className="header-actions">
          <HealthBadge health={health} />
          <button type="button" className="button-secondary" onClick={handleNewChat} disabled={sending}>
            New chat
          </button>
        </div>
      </header>

      <div className="layout">
        <SettingsPanel
          systemPrompt={systemPrompt}
          onSystemPromptChange={setSystemPrompt}
          promptLocked={promptLocked}
          simulate={simulate}
          onSimulateChange={setSimulate}
        />

        <main className="chat">
          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <p className="empty-state">Send a message to start the conversation.</p>
            )}
            {/* The list only grows (or is fully reset), so the index is a safe key */}
            {messages.map((message, index) => (
              <ChatMessage key={index} message={message} />
            ))}
            {sending && <div className="message pending">Thinking…</div>}
            <div ref={bottomRef} />
          </div>

          <Composer value={input} onChange={setInput} onSend={handleSend} sending={sending} />
        </main>
      </div>
    </div>
  )
}

function HealthBadge({ health }) {
  if (health === 'checking') return <span className="health health-checking">Checking backend…</span>
  if (!health) return <span className="health health-down">Backend unreachable</span>
  return (
    <span className="health health-ok">
      Backend online · {health.keys_configured} keys · cache {health.cache_enabled ? 'on' : 'off'}
    </span>
  )
}
