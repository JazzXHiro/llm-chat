// One bubble in the chat: a user message, an assistant reply (with metadata) or an error.
export default function ChatMessage({ message }) {
  if (message.role === 'assistant') {
    return (
      <div className="message assistant" data-testid="assistant-message">
        <p className="message-text">{message.content}</p>
        <MetaRow metadata={message.metadata} />
      </div>
    )
  }

  if (message.role === 'error') {
    return (
      <div className="message error" role="alert" data-testid="error-message">
        <strong>{message.status ? `Error ${message.status}` : 'Connection error'}</strong>
        <p className="message-text">{message.content}</p>
      </div>
    )
  }

  // user message (whitespace-only text is shown as a hint so the bubble is not blank)
  return (
    <div className="message user">
      <p className="message-text">{message.content.trim() ? message.content : '(empty message)'}</p>
    </div>
  )
}

// Metadata of this one request, shown under each assistant reply
function MetaRow({ metadata }) {
  const fromCache = metadata.resolution_source === 'LLM_CACHE'

  return (
    <div className="meta">
      <span className={`badge ${fromCache ? 'badge-cache' : 'badge-live'}`} data-testid="meta-source">
        {metadata.resolution_source}
      </span>
      <MetaItem label="Model" testId="meta-model" value={metadata.model} />
      <MetaItem label="Latency" testId="meta-latency" value={`${metadata.latency_ms} ms`} />
      <MetaItem label="In" testId="meta-input-tokens" value={metadata.input_tokens} />
      <MetaItem label="Out" testId="meta-output-tokens" value={metadata.output_tokens} />
      <MetaItem label="Key" testId="meta-key-id" value={metadata.key_id ?? 'none'} />
      <MetaItem label="Fallbacks" testId="meta-fallback-attempts" value={metadata.fallback_attempts} />
    </div>
  )
}

// "Label value" pair; the testid sits on the value only, so its text is exactly the value
function MetaItem({ label, testId, value }) {
  return (
    <span className="meta-item">
      <span className="meta-label">{label}</span>
      <span data-testid={testId}>{value}</span>
    </span>
  )
}
