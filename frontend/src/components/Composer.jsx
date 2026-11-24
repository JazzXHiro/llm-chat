// Message box + Send button at the bottom of the chat.
// Enter sends, Shift+Enter adds a new line.
export default function Composer({ value, onChange, onSend, sending }) {
  function handleKeyDown(event) {
    // isComposing: ignore Enter while an IME (e.g. Hindi/Japanese keyboard) is still composing
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      onSend()
    }
  }

  function handleSubmit(event) {
    event.preventDefault()
    onSend()
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        data-testid="chat-input"
        className="composer-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
        rows={2}
        aria-label="Message"
        autoFocus
      />
      <button type="submit" data-testid="send-button" className="button-primary" disabled={sending}>
        {sending ? 'Sending…' : 'Send'}
      </button>
    </form>
  )
}
